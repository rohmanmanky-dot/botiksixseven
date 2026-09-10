"""Перекличка: кнопки под напоминанием и «+»/«−» текстом в чате."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji

from ..db import STATUS_LABELS
from ..keyboards import parse_vote_callback
from ..service import AttendanceService

log = logging.getLogger(__name__)

router = Router(name="attendance")

MARKS: dict[str, str] = {
    "+": "yes", "＋": "yes", "➕": "yes", "+1": "yes", "плюс": "yes",
    "буду": "yes", "я буду": "yes", "да": "yes", "✅": "yes",
    "-": "no", "−": "no", "–": "no", "—": "no", "➖": "no", "-1": "no",
    "минус": "no", "не буду": "no", "нет": "no", "❌": "no",
    "?": "late", "опоздаю": "late", "опаздываю": "late", "🕐": "late",
}

ACK_EMOJI = {"yes": "👍", "no": "👌", "late": "🤝"}

MAX_MARK_LENGTH = 12


def parse_mark(text: str | None) -> str | None:
    """«+», «минус», «буду» → статус переклички. Всё остальное — None."""
    if not text:
        return None
    key = text.strip().lower().replace("ё", "е")
    if len(key) > MAX_MARK_LENGTH:
        return None
    return MARKS.get(key)


@router.callback_query(F.data.startswith("att:"))
async def on_vote_button(callback: CallbackQuery, service: AttendanceService) -> None:
    parsed = parse_vote_callback(callback.data or "")
    if parsed is None or callback.from_user is None:
        await callback.answer()
        return

    status, occurrence_key = parsed
    if service.schedule.occurrence_by_key(occurrence_key) is None:
        await callback.answer(
            "Эта пара пропала из расписания — перекличка неактуальна.", show_alert=True
        )
        return

    result = await service.register_vote(
        occurrence_key,
        callback.from_user.id,
        callback.from_user.full_name,
        callback.from_user.username,
        status,
    )
    if result == "cleared":
        await callback.answer("Отметку снял — нажмите ещё раз, чтобы поставить.")
    else:
        await callback.answer(f"Записал: {STATUS_LABELS[status]}")


@router.message(F.text.func(lambda text: parse_mark(text) is not None))
async def on_plus_minus(message: Message, service: AttendanceService) -> None:
    """Молча игнорируем «+», если активной переклички нет — чат не засоряем."""
    status = parse_mark(message.text)
    if status is None or message.from_user is None:
        return

    poll = None
    if message.reply_to_message is not None:
        poll = await service.db.poll_by_message(
            message.chat.id, message.reply_to_message.message_id
        )
    if poll is None:
        poll = await service.db.latest_open_poll(message.chat.id, service.now())
    if poll is None:
        return

    result = await service.register_vote(
        poll["occurrence_key"],
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username,
        status,
    )
    if result == "cleared":
        await message.reply("Снял вашу отметку.")
        return

    try:
        await service.bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=ACK_EMOJI[status])],
        )
    except TelegramBadRequest:
        log.debug("Реакции недоступны в чате %s — отметка всё равно записана", message.chat.id)
