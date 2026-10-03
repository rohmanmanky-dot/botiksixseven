"""Тесты листания расписания: кнопки под /today и /week."""

from __future__ import annotations

from datetime import date

from bot.keyboards import (
    day_nav_keyboard,
    nav_callback,
    parse_nav_callback,
    short_day,
    week_nav_keyboard,
    week_start,
)
from bot.texts import render_day

TODAY = date(2026, 10, 7)  # среда


def buttons(keyboard):
    return [[(b.text, b.callback_data) for b in row] for row in keyboard.inline_keyboard]


def test_short_day_fits_into_button():
    assert short_day(date(2026, 10, 6)) == "вт, 6 окт"
    assert short_day(date(2026, 5, 1)) == "пт, 1 мая"


def test_nav_callback_round_trip():
    data = nav_callback("day", date(2026, 10, 8))
    assert data == "nav:day:2026-10-08"
    assert len(data.encode()) <= 64  # лимит Telegram на callback_data
    assert parse_nav_callback(data, TODAY) == ("day", date(2026, 10, 8))


def test_week_callback_snaps_to_monday():
    assert parse_nav_callback("nav:week:2026-10-09", TODAY) == ("week", date(2026, 10, 5))


def test_garbage_and_far_dates_are_rejected():
    for data in [
        "nav:day",
        "nav:month:2026-10-07",
        "nav:day:вчера",
        "att:yes:x",
        "nav:day:2030-01-01",
    ]:
        assert parse_nav_callback(data, TODAY) is None


def test_today_view_has_no_today_button():
    rows = buttons(day_nav_keyboard(TODAY, TODAY))
    assert rows[0] == [
        ("◀ вт, 6 окт", "nav:day:2026-10-06"),
        ("чт, 8 окт ▶", "nav:day:2026-10-08"),
    ]
    assert rows[1] == [("🗓 Вся неделя", "nav:week:2026-10-05")]


def test_other_day_offers_jump_back_to_today():
    rows = buttons(day_nav_keyboard(date(2026, 10, 12), TODAY))
    assert ("• Сегодня", "nav:day:2026-10-07") in rows[0]
    assert rows[1] == [("🗓 Вся неделя", "nav:week:2026-10-12")]


def test_week_navigation():
    current = week_start(TODAY)
    rows = buttons(week_nav_keyboard(current, TODAY))
    assert [text for text, _ in rows[0]] == ["◀ Пред. неделя", "След. неделя ▶"]
    assert rows[1] == [("📅 По дням: ср, 7 окт", "nav:day:2026-10-07")]

    rows = buttons(week_nav_keyboard(date(2026, 10, 19), TODAY))
    assert rows[0][0][1] == "nav:week:2026-10-12"
    assert ("• Эта неделя", "nav:week:2026-10-05") in rows[0]
    assert rows[0][-1][1] == "nav:week:2026-10-26"
    assert rows[1] == [("📅 По дням: пн, 19 окт", "nav:day:2026-10-19")]


def test_day_header_says_relative_day():
    assert "· завтра" in render_day(date(2026, 10, 8), [], today=TODAY)
    assert "· сегодня" in render_day(TODAY, [], today=TODAY)
    assert "·" not in render_day(date(2026, 10, 20), [], today=TODAY).splitlines()[0]
    assert "·" not in render_day(TODAY, []).splitlines()[0]
