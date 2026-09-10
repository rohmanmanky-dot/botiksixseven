"""Инлайн-кнопки переклички."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_PREFIX = "att"


def vote_callback(status: str, occurrence_key: str) -> str:
    return f"{CALLBACK_PREFIX}:{status}:{occurrence_key}"


def parse_vote_callback(data: str) -> tuple[str, str] | None:
    """`att:<статус>:<ключ занятия>` → (статус, ключ)."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    return parts[1], parts[2]


def attendance_keyboard(occurrence_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Буду", callback_data=vote_callback("yes", occurrence_key)
                ),
                InlineKeyboardButton(
                    text="❌ Не буду", callback_data=vote_callback("no", occurrence_key)
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🕐 Опоздаю", callback_data=vote_callback("late", occurrence_key)
                ),
            ],
        ]
    )
