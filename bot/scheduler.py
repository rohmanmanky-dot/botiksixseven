"""Планировщик: ставит напоминания на все пары ближайших дней."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .config import Settings
from .service import AttendanceService
from .texts import render_day

log = logging.getLogger(__name__)

PLAN_AHEAD_DAYS = 2
MISFIRE_GRACE_SECONDS = 600


class ReminderScheduler:
    """Раз в сутки (и на старте) раскладывает задачи по каждому занятию."""

    def __init__(self, service: AttendanceService, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)

    async def start(self) -> None:
        self.scheduler.add_job(
            self.plan,
            CronTrigger(hour=0, minute=5, timezone=self.settings.timezone),
            id="planner",
            replace_existing=True,
        )
        if self.settings.digest_at is not None:
            self.scheduler.add_job(
                self.send_digest,
                CronTrigger(
                    hour=self.settings.digest_at.hour,
                    minute=self.settings.digest_at.minute,
                    timezone=self.settings.timezone,
                ),
                id="digest",
                replace_existing=True,
                misfire_grace_time=MISFIRE_GRACE_SECONDS,
            )
        self.scheduler.start()
        await self.plan()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def plan(self, days: int = PLAN_AHEAD_DAYS) -> int:
        """Ставит (или переставляет) задачи на сегодня и ближайшие дни."""
        now = self.service.now()
        planned = 0
        for offset in range(days + 1):
            day = now.date() + timedelta(days=offset)
            for occurrence in self.service.schedule.occurrences_on(day):
                planned += int(self._plan_occurrence(occurrence, now))
        log.info("Запланировано напоминаний: %s", planned)
        return planned

    def _plan_occurrence(self, occurrence, now: datetime) -> bool:
        if occurrence.start_at <= now:
            return False

        run_at = max(occurrence.remind_at, now + timedelta(seconds=5))
        self.scheduler.add_job(
            self.service.send_poll,
            DateTrigger(run_date=run_at, timezone=self.settings.timezone),
            args=[occurrence],
            id=f"remind:{occurrence.key}",
            replace_existing=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )

        close_at = occurrence.start_at + timedelta(minutes=self.settings.summary_after_minutes)
        if close_at > now:
            self.scheduler.add_job(
                self.service.close_poll,
                DateTrigger(run_date=close_at, timezone=self.settings.timezone),
                args=[occurrence.key],
                id=f"close:{occurrence.key}",
                replace_existing=True,
                misfire_grace_time=MISFIRE_GRACE_SECONDS,
            )
        return True

    async def send_digest(self, day: date | None = None) -> None:
        """Утреннее сообщение со списком пар на день — только если пары есть."""
        chat_id = await self.service.target_chat_id()
        if chat_id is None:
            return
        day = day or self.service.now().date()
        occurrences = self.service.schedule.occurrences_on(day)
        if not occurrences:
            return
        await self.service.bot.send_message(
            chat_id,
            "☀️ <b>Доброе утро!</b>\n\n" + render_day(day, occurrences),
            disable_web_page_preview=True,
        )
