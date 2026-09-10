"""Тексты сообщений бота (HTML parse mode)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

from .db import Vote
from .roster import Roster, normalize_name
from .schedule import Occurrence, Schedule, WEEKDAY_NAMES

MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

MAX_NAMES_IN_LIST = 30

HELP_TEXT = """<b>Что я умею</b>

Напоминаю о пáрах за 30 минут до начала и собираю перекличку для старосты.
Отметиться можно кнопкой под напоминанием или просто написать в чат
<code>+</code> (буду) или <code>-</code> (не буду) — засчитаю в последнюю перекличку.

<b>Команды для всех</b>
/today — расписание на сегодня
/tomorrow — расписание на завтра
/next — ближайшая пара
/week — расписание на неделю
/me Иванов Иван — представиться, чтобы староста видел ФИО, а не ник
/whoami — показать свой Telegram ID

<b>Команды старосты</b>
/here — привязать бота к этому чату
/ask — запустить перекличку по ближайшей паре прямо сейчас
/report — отчёт за сегодня (/report 2026-09-12 — за дату)
/export — выгрузка отчёта в CSV
/reload — перечитать файл расписания
"""


def fmt_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}, {WEEKDAY_NAMES[day.weekday()]}"


def _plural(number: int, one: str, few: str, many: str) -> str:
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def fmt_minutes(minutes: int) -> str:
    if minutes <= 0:
        return "уже началась"
    if minutes < 60:
        return f"через {minutes} {_plural(minutes, 'минуту', 'минуты', 'минут')}"
    hours, rest = divmod(minutes, 60)
    tail = f" {rest} мин" if rest else ""
    return f"через {hours} {_plural(hours, 'час', 'часа', 'часов')}{tail}"


def lesson_header(occurrence: Occurrence) -> str:
    lesson = occurrence.lesson
    lines = [
        f"{lesson.emoji} <b>{escape(lesson.title)}</b> — {lesson.kind_title.lower()}",
        f"🕘 {occurrence.time_range}",
    ]
    details = []
    if lesson.location:
        details.append(escape(lesson.location))
    if lesson.teacher:
        details.append(escape(lesson.teacher))
    if details:
        lines.append("📍 " + " · ".join(details))
    if lesson.link:
        lines.append(f'🔗 <a href="{escape(lesson.link, quote=True)}">ссылка на пару</a>')
    if lesson.note:
        lines.append(f"ℹ️ {escape(lesson.note)}")
    return "\n".join(lines)


def _names(votes: list[Vote]) -> list[str]:
    return [escape(vote.full_name) for vote in votes]


def _name_list(names: list[str]) -> str:
    if not names:
        return "—"
    if len(names) <= MAX_NAMES_IN_LIST:
        return ", ".join(names)
    shown = ", ".join(names[:MAX_NAMES_IN_LIST])
    return f"{shown} и ещё {len(names) - MAX_NAMES_IN_LIST}"


def render_poll(
    occurrence: Occurrence,
    votes: list[Vote],
    roster: Roster,
    *,
    minutes_left: int | None = None,
    closed: bool = False,
) -> str:
    """Сообщение-перекличка: шапка пары, кто «+», кто «−», кто молчит."""
    by_status: dict[str, list[Vote]] = {"yes": [], "no": [], "late": []}
    for vote in votes:
        by_status.setdefault(vote.status, []).append(vote)

    if closed:
        title = "📋 <b>Итог переклички</b>"
    elif minutes_left is None:
        title = "🔔 <b>Перекличка</b>"
    else:
        title = f"🔔 <b>Пара {escape(fmt_minutes(minutes_left))}</b>"

    lines = [
        title,
        "",
        lesson_header(occurrence),
        f"📅 {fmt_date(occurrence.day)}",
        "",
        f"✅ Будут ({len(by_status['yes'])}): {_name_list(_names(by_status['yes']))}",
        f"❌ Не будут ({len(by_status['no'])}): {_name_list(_names(by_status['no']))}",
    ]
    if by_status["late"]:
        lines.append(
            f"🕐 Опоздают ({len(by_status['late'])}): {_name_list(_names(by_status['late']))}"
        )

    if roster:
        missing = roster.missing(
            answered_names={vote.full_name for vote in votes},
            answered_ids={vote.user_id for vote in votes},
        )
        if missing:
            lines.append(
                f"🤔 Не ответили ({len(missing)}): "
                f"{_name_list([escape(name) for name in missing])}"
            )
        else:
            lines.append("🎉 Ответили все!")

    lines.append("")
    lines.append(
        "Отметьтесь для старосты: кнопкой ниже или напишите в чат <code>+</code> / <code>-</code>."
        if not closed
        else "Перекличка закрыта, но отметиться ещё можно."
    )
    return "\n".join(lines)


def render_day(
    day: date, occurrences: list[Occurrence], *, empty_note: str | None = None
) -> str:
    if not occurrences:
        return f"📅 <b>{fmt_date(day)}</b>\n\n{empty_note or 'Пар нет. Отдыхаем 🎉'}"
    lines = [f"📅 <b>{fmt_date(day)}</b>", ""]
    for occurrence in occurrences:
        lesson = occurrence.lesson
        parts = [f"{occurrence.time_range} — {lesson.emoji} <b>{escape(lesson.title)}</b>"]
        tail = [lesson.kind_title.lower()]
        if lesson.location:
            tail.append(escape(lesson.location))
        parts.append(f"   {' · '.join(tail)}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def render_week(schedule: Schedule, monday: date) -> str:
    header = "🗓 <b>Расписание на неделю</b>"
    if schedule.group_name:
        header += f" — {escape(schedule.group_name)}"
    blocks = [header]
    for offset in range(7):
        day = monday + timedelta(days=offset)
        occurrences = schedule.occurrences_on(day)
        if not occurrences:
            continue
        rows = [f"<b>{WEEKDAY_NAMES[day.weekday()].capitalize()}, {day.day} {MONTHS[day.month - 1]}</b>"]
        for occurrence in occurrences:
            lesson = occurrence.lesson
            rows.append(
                f"{occurrence.time_range} — {lesson.emoji} {escape(lesson.title)}"
                f" ({lesson.kind_title.lower()})"
            )
        blocks.append("\n".join(rows))
    if len(blocks) == 1:
        blocks.append("На этой неделе пар нет.")
    return "\n\n".join(blocks)


def render_next(occurrence: Occurrence | None, now: datetime) -> str:
    if occurrence is None:
        return "Ближайших пар в расписании нет 🎉"
    minutes = int((occurrence.start_at - now).total_seconds() // 60)
    return "\n".join(
        [
            f"⏭ <b>Ближайшая пара</b> — {escape(fmt_minutes(minutes))}",
            "",
            lesson_header(occurrence),
            f"📅 {fmt_date(occurrence.day)}",
        ]
    )


def render_report(
    day: date,
    items: list[tuple[Occurrence, list[Vote]]],
    roster: Roster,
) -> str:
    """Сводка по всем парам дня — то, что староста перенесёт в отчётность."""
    if not items:
        return f"📊 <b>Отчёт за {fmt_date(day)}</b>\n\nВ этот день пар не было."

    blocks = [f"📊 <b>Отчёт за {fmt_date(day)}</b>"]
    for occurrence, votes in items:
        by_status: dict[str, list[Vote]] = {"yes": [], "no": [], "late": []}
        for vote in votes:
            by_status.setdefault(vote.status, []).append(vote)

        rows = [
            f"{occurrence.time_range} — {occurrence.lesson.emoji} "
            f"<b>{escape(occurrence.lesson.title)}</b> ({occurrence.lesson.kind_title.lower()})",
            f"✅ Будут ({len(by_status['yes'])}): {_name_list(_names(by_status['yes']))}",
            f"❌ Не будут ({len(by_status['no'])}): {_name_list(_names(by_status['no']))}",
        ]
        if by_status["late"]:
            rows.append(
                f"🕐 Опоздают ({len(by_status['late'])}): "
                f"{_name_list(_names(by_status['late']))}"
            )
        if roster:
            missing = roster.missing(
                answered_names={vote.full_name for vote in votes},
                answered_ids={vote.user_id for vote in votes},
            )
            if missing:
                rows.append(
                    f"🤔 Молчат ({len(missing)}): "
                    f"{_name_list([escape(name) for name in missing])}"
                )
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def csv_rows(
    day: date,
    items: list[tuple[Occurrence, list[Vote]]],
    roster: Roster,
) -> list[list[str]]:
    """Строки CSV-выгрузки: одна строка — один студент на одной паре."""
    rows: list[list[str]] = [
        ["Дата", "Время", "Предмет", "Тип", "ФИО", "Ник", "Отметка"]
    ]
    for occurrence, votes in items:
        answered_keys = {normalize_name(vote.full_name) for vote in votes}
        answered_ids = {vote.user_id for vote in votes}
        base = [
            day.isoformat(),
            occurrence.time_range,
            occurrence.lesson.title,
            occurrence.lesson.kind_title,
        ]
        for vote in votes:
            mark = {"yes": "+", "no": "-", "late": "опоздает"}.get(vote.status, vote.status)
            rows.append([*base, vote.full_name, vote.username or "", mark])
        for student in roster.students:
            if student.key in answered_keys:
                continue
            if student.telegram_id is not None and student.telegram_id in answered_ids:
                continue
            rows.append([*base, student.name, "", "нет ответа"])
    return rows
