"""Инлайн-кнопки: перекличка и листание расписания."""

from __future__ import annotations

from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_PREFIX = "att"
NAV_PREFIX = "nav"
NAV_VIEWS = ("day", "week")

# Дальше года от сегодняшнего дня листать незачем — заодно отсекаем мусор в callback.
NAV_MAX_DAYS = 366

SHORT_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
SHORT_MONTHS = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


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


# ----------------------------------------------------------- листание расписания


def nav_callback(view: str, day: date) -> str:
    return f"{NAV_PREFIX}:{view}:{day.isoformat()}"


def parse_nav_callback(data: str, today: date) -> tuple[str, date] | None:
    """`nav:<day|week>:<YYYY-MM-DD>` → (вид, дата). Для недели дата — её понедельник."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != NAV_PREFIX or parts[1] not in NAV_VIEWS:
        return None
    try:
        day = date.fromisoformat(parts[2])
    except ValueError:
        return None
    if abs((day - today).days) > NAV_MAX_DAYS:
        return None
    view = parts[1]
    if view == "week":
        day = week_start(day)
    return view, day


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def short_day(day: date) -> str:
    """«вт, 6 окт» — коротко, чтобы влезло в кнопку на телефоне."""
    return f"{SHORT_WEEKDAYS[day.weekday()]}, {day.day} {SHORT_MONTHS[day.month - 1]}"


def _nav_button(text: str, view: str, day: date) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=nav_callback(view, day))


def day_nav_keyboard(day: date, today: date) -> InlineKeyboardMarkup:
    """Под расписанием на день: ◀ вчера · сегодня · завтра ▶ и переход к неделе."""
    prev_day, next_day = day - timedelta(days=1), day + timedelta(days=1)
    row = [_nav_button(f"◀ {short_day(prev_day)}", "day", prev_day)]
    if day != today:
        row.append(_nav_button("• Сегодня", "day", today))
    row.append(_nav_button(f"{short_day(next_day)} ▶", "day", next_day))
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [_nav_button("🗓 Вся неделя", "week", week_start(day))]]
    )


def week_nav_keyboard(monday: date, today: date) -> InlineKeyboardMarkup:
    """Под расписанием на неделю: ◀ прошлая · эта · следующая ▶ и переход к дню."""
    current = week_start(today)
    row = [_nav_button("◀ Пред. неделя", "week", monday - timedelta(days=7))]
    if monday != current:
        row.append(_nav_button("• Эта неделя", "week", current))
    row.append(_nav_button("След. неделя ▶", "week", monday + timedelta(days=7)))
    # Из текущей недели — к сегодняшнему дню, из любой другой — к её понедельнику.
    target = today if monday == current else monday
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [_nav_button(f"📅 По дням: {short_day(target)}", "day", target)]]
    )
