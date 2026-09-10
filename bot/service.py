"""Связующий слой: рассылка переклички, учёт ответов, отчёты для старосты."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .config import Settings
from .db import Database, Vote
from .keyboards import attendance_keyboard
from .roster import Roster, load_roster
from .schedule import Occurrence, Schedule, ScheduleHolder
from .texts import render_poll, render_report

log = logging.getLogger(__name__)

CHAT_SETTING_KEY = "chat_id"
DEFAULT_LESSON_MINUTES = 90


class AttendanceService:
    """Всё, что бот делает с перекличкой, живёт здесь — хендлеры только зовут методы."""

    def __init__(
        self,
        bot: Bot,
        db: Database,
        holder: ScheduleHolder,
        settings: Settings,
        roster: Roster,
    ) -> None:
        self.bot = bot
        self.db = db
        self.holder = holder
        self.settings = settings
        self.roster = roster

    @property
    def schedule(self) -> Schedule:
        return self.holder.schedule

    def now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    # ------------------------------------------------------------ чат группы

    async def target_chat_id(self) -> int | None:
        """Куда слать напоминания: из .env или из /here."""
        if self.settings.chat_id is not None:
            return self.settings.chat_id
        stored = await self.db.get_setting(CHAT_SETTING_KEY)
        return int(stored) if stored else None

    async def set_target_chat(self, chat_id: int) -> None:
        await self.db.set_setting(CHAT_SETTING_KEY, str(chat_id))

    # -------------------------------------------------------------- перекличка

    def closes_at(self, occurrence: Occurrence) -> datetime:
        if occurrence.end_at is not None:
            return occurrence.end_at
        return occurrence.start_at + timedelta(minutes=DEFAULT_LESSON_MINUTES)

    async def send_poll(self, occurrence: Occurrence, chat_id: int | None = None) -> bool:
        """Публикует напоминание с кнопками. Повторный вызов обновляет старое сообщение."""
        if chat_id is None:
            chat_id = await self.target_chat_id()
        if chat_id is None:
            log.warning("Некуда слать перекличку: чат не задан (CHAT_ID или /here)")
            return False

        existing = await self.db.get_poll(occurrence.key)
        if existing is not None and existing["chat_id"] == chat_id:
            await self.refresh_poll(occurrence.key)
            return True

        minutes_left = int((occurrence.start_at - self.now()).total_seconds() // 60)
        votes = await self.db.get_votes(occurrence.key)
        text = render_poll(occurrence, votes, self.roster, minutes_left=minutes_left)
        try:
            message = await self.bot.send_message(
                chat_id,
                text,
                reply_markup=attendance_keyboard(occurrence.key),
                disable_web_page_preview=True,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            log.error("Не удалось отправить перекличку в чат %s: %s", chat_id, exc)
            return False

        await self.db.save_poll(
            occurrence.key, chat_id, message.message_id, self.closes_at(occurrence)
        )
        try:
            await self.bot.pin_chat_message(
                chat_id, message.message_id, disable_notification=True
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            log.debug("Нет прав закрепить сообщение в чате %s — не страшно", chat_id)
        return True

    async def refresh_poll(self, occurrence_key: str, *, closed: bool = False) -> None:
        """Перерисовывает сообщение переклички после нового ответа."""
        poll = await self.db.get_poll(occurrence_key)
        occurrence = self.schedule.occurrence_by_key(occurrence_key)
        if poll is None or occurrence is None:
            return

        votes = await self.db.get_votes(occurrence_key)
        minutes_left = int((occurrence.start_at - self.now()).total_seconds() // 60)
        text = render_poll(
            occurrence,
            votes,
            self.roster,
            minutes_left=None if closed else minutes_left,
            closed=closed,
        )
        try:
            await self.bot.edit_message_text(
                text,
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                reply_markup=attendance_keyboard(occurrence_key),
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                log.warning("Не удалось обновить перекличку %s: %s", occurrence_key, exc)

    async def register_vote(
        self,
        occurrence_key: str,
        user_id: int,
        full_name: str,
        username: str | None,
        status: str,
    ) -> str:
        """Ставит отметку. Повторное нажатие того же статуса снимает её."""
        await self.db.remember_user(user_id, full_name, username)
        current = next(
            (vote for vote in await self.db.get_votes(occurrence_key) if vote.user_id == user_id),
            None,
        )
        if current is not None and current.status == status:
            await self.db.clear_vote(occurrence_key, user_id)
            result = "cleared"
        else:
            await self.db.set_vote(occurrence_key, user_id, status)
            result = "saved"
        await self.refresh_poll(occurrence_key)
        return result

    async def close_poll(self, occurrence_key: str) -> None:
        """Подводит итог: правит сообщение и шлёт сводку старостам в личку."""
        occurrence = self.schedule.occurrence_by_key(occurrence_key)
        if occurrence is None or await self.db.get_poll(occurrence_key) is None:
            return
        await self.refresh_poll(occurrence_key, closed=True)
        votes = await self.db.get_votes(occurrence_key)
        text = render_report(occurrence.day, [(occurrence, votes)], self.roster)
        await self.notify_admins(text)

    async def notify_admins(self, text: str) -> None:
        for admin_id in sorted(self.settings.admin_ids):
            try:
                await self.bot.send_message(admin_id, text, disable_web_page_preview=True)
            except (TelegramBadRequest, TelegramForbiddenError):
                log.debug("Староста %s не начинал диалог с ботом — сводку не шлём", admin_id)

    # ------------------------------------------------------------------ отчёты

    async def report_items(self, day: date) -> list[tuple[Occurrence, list[Vote]]]:
        occurrences = self.schedule.occurrences_on(day)
        return [(occurrence, await self.db.get_votes(occurrence.key)) for occurrence in occurrences]

    async def next_occurrence(self, now: datetime | None = None) -> Occurrence | None:
        upcoming = self.schedule.upcoming(now or self.now())
        return upcoming[0] if upcoming else None

    # ---------------------------------------------------------------- перезагрузка

    def reload(self) -> Schedule:
        schedule = self.holder.reload()
        self.roster = load_roster(self.settings.roster_path)
        return schedule
