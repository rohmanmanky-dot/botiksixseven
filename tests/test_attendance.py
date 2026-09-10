"""Тесты переклички: разбор «+/-», кнопки, хранение отметок и отчёты."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.db import Database
from bot.handlers.attendance import parse_mark
from bot.keyboards import attendance_keyboard, parse_vote_callback, vote_callback
from bot.roster import parse_roster
from bot.schedule import parse_schedule
from bot.texts import csv_rows, fmt_minutes, render_poll, render_report

MSK = ZoneInfo("Europe/Moscow")

SCHEDULE = parse_schedule(
    {
        "lessons": [
            {
                "id": "algo-sem",
                "title": "Алгоритмы",
                "kind": "seminar",
                "weekday": "mon",
                "start": "09:30",
                "end": "10:50",
                "location": "ауд. 317",
            }
        ]
    },
    default_timezone=MSK,
)

OCCURRENCE = SCHEDULE.occurrences_on(date(2026, 9, 7))[0]
ROSTER = parse_roster(["Ахмедов Рахман", "Борисова Анна", "Гаджиев Ислам"])


@pytest.mark.parametrize("text", ["+", " + ", "+1", "плюс", "буду", "да", "✅"])
def test_plus_forms_mean_yes(text):
    assert parse_mark(text) == "yes"


@pytest.mark.parametrize("text", ["-", "−", "–", "—", "-1", "минус", "не буду", "нет", "❌"])
def test_minus_forms_mean_no(text):
    assert parse_mark(text) == "no"


@pytest.mark.parametrize("text", ["опоздаю", "Опаздываю", "?"])
def test_late_forms(text):
    assert parse_mark(text) == "late"


@pytest.mark.parametrize(
    "text", ["", None, "привет", "+++", "плюс минус", "а" * 50, "+ буду на паре"]
)
def test_other_messages_are_ignored(text):
    assert parse_mark(text) is None


def test_callback_roundtrip_fits_telegram_limit():
    data = vote_callback("late", OCCURRENCE.key)
    assert len(data.encode()) <= 64
    assert parse_vote_callback(data) == ("late", OCCURRENCE.key)


def test_callback_rejects_foreign_data():
    assert parse_vote_callback("other:yes:key") is None
    assert parse_vote_callback("att:yes") is None


def test_keyboard_has_three_options():
    buttons = [b for row in attendance_keyboard(OCCURRENCE.key).inline_keyboard for b in row]
    assert len(buttons) == 3
    assert {parse_vote_callback(b.callback_data)[0] for b in buttons} == {"yes", "no", "late"}


def test_poll_lists_votes_and_silent_students():
    votes = _votes([("Ахмедов Рахман", "yes"), ("Борисова Анна", "no")])
    text = render_poll(OCCURRENCE, votes, ROSTER, minutes_left=30)
    assert "Алгоритмы" in text
    assert "09:30–10:50" in text
    assert "✅ Будут (1): Ахмедов Рахман" in text
    assert "❌ Не будут (1): Борисова Анна" in text
    assert "🤔 Не ответили (1): Гаджиев Ислам" in text


def test_poll_congratulates_when_everyone_answered():
    votes = _votes([(student.name, "yes") for student in ROSTER.students])
    assert "Ответили все!" in render_poll(OCCURRENCE, votes, ROSTER, minutes_left=5)


def test_poll_escapes_html_in_names():
    votes = _votes([("<b>Хакер</b>", "yes")])
    text = render_poll(OCCURRENCE, votes, ROSTER, minutes_left=5)
    assert "<b>Хакер</b>" not in text
    assert "&lt;b&gt;Хакер&lt;/b&gt;" in text


def test_closed_poll_says_it_is_a_summary():
    text = render_poll(OCCURRENCE, [], ROSTER, closed=True)
    assert "Итог переклички" in text


def test_report_covers_every_lesson_of_the_day():
    report = render_report(OCCURRENCE.day, [(OCCURRENCE, _votes([("Ахмедов Рахман", "yes")]))], ROSTER)
    assert "Отчёт за 7 сентября, понедельник" in report
    assert "Алгоритмы" in report
    assert "🤔 Молчат (2)" in report


def test_report_without_lessons():
    assert "пар не было" in render_report(date(2026, 9, 6), [], ROSTER)


def test_csv_has_a_row_per_student_including_silent_ones():
    rows = csv_rows(OCCURRENCE.day, [(OCCURRENCE, _votes([("Ахмедов Рахман", "yes")]))], ROSTER)
    assert rows[0][0] == "Дата"
    body = rows[1:]
    assert len(body) == 3
    assert body[0][-1] == "+"
    assert {row[-1] for row in body[1:]} == {"нет ответа"}


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "уже началась"), (1, "через 1 минуту"), (3, "через 3 минуты"),
     (30, "через 30 минут"), (60, "через 1 час"), (95, "через 1 час 35 мин")],
)
def test_minutes_are_declined_properly(minutes, expected):
    assert fmt_minutes(minutes) == expected


def test_votes_survive_restart_and_can_be_changed(tmp_path):
    asyncio.run(_db_scenario(tmp_path / "test.sqlite3"))


async def _db_scenario(path):
    db = Database(path)
    await db.connect()
    try:
        key = OCCURRENCE.key
        await db.remember_user(1, "Рахман", "rakhman")
        await db.set_vote(key, 1, "yes")
        assert [(v.user_id, v.status) for v in await db.get_votes(key)] == [(1, "yes")]

        # Передумал — отметка перезаписывается, а не дублируется.
        await db.set_vote(key, 1, "no")
        votes = await db.get_votes(key)
        assert len(votes) == 1 and votes[0].status == "no"
        assert votes[0].full_name == "Рахман"

        # /me фиксирует ФИО, и автоматика его больше не затирает.
        await db.remember_user(1, "Ахмедов Рахман", "rakhman", linked=True)
        await db.remember_user(1, "Rakhman", "rakhman")
        assert (await db.get_votes(key))[0].full_name == "Ахмедов Рахман"

        await db.clear_vote(key, 1)
        assert await db.get_votes(key) == []

        # Перекличка находится по сообщению и как последняя открытая в чате.
        now = datetime(2026, 9, 7, 9, 10, tzinfo=MSK)
        await db.save_poll(key, -100500, 777, now + timedelta(hours=1))
        assert (await db.poll_by_message(-100500, 777))["occurrence_key"] == key
        assert (await db.latest_open_poll(-100500, now))["message_id"] == 777
        assert await db.latest_open_poll(-100500, now + timedelta(hours=2)) is None

        with pytest.raises(ValueError):
            await db.set_vote(key, 1, "может быть")
    finally:
        await db.close()


def _votes(pairs):
    from bot.db import Vote

    return [
        Vote(user_id=index + 1, status=status, full_name=name, username=None, updated_at="")
        for index, (name, status) in enumerate(pairs)
    ]
