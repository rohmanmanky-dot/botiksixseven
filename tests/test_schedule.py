"""Тесты разбора расписания и вычисления занятий по дням."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bot.schedule import (
    ScheduleError,
    load_schedule,
    parse_kind,
    parse_schedule,
    parse_weekday,
    study_week,
)

MSK = ZoneInfo("Europe/Moscow")
EXAMPLE = Path("config/schedule.example.json")


def build(**overrides):
    lesson = {
        "id": "matan",
        "title": "Математический анализ",
        "kind": "lecture",
        "weekday": "mon",
        "start": "09:30",
        "end": "10:50",
    }
    lesson.update(overrides)
    return parse_schedule({"lessons": [lesson]}, default_timezone=MSK)


def test_weekly_lesson_lands_on_its_weekday():
    schedule = build()
    monday = date(2026, 9, 7)
    assert len(schedule.occurrences_on(monday)) == 1
    assert schedule.occurrences_on(monday + timedelta(days=1)) == []


def test_occurrence_times_are_timezone_aware():
    occurrence = build().occurrences_on(date(2026, 9, 7))[0]
    assert occurrence.start_at == datetime(2026, 9, 7, 9, 30, tzinfo=MSK)
    assert occurrence.end_at == datetime(2026, 9, 7, 10, 50, tzinfo=MSK)
    assert occurrence.time_range == "09:30–10:50"


def test_reminder_uses_lesson_override_over_default():
    schedule = build(remind_before_minutes=60)
    occurrence = schedule.occurrences_on(date(2026, 9, 7))[0]
    assert occurrence.remind_at == datetime(2026, 9, 7, 8, 30, tzinfo=MSK)

    default = parse_schedule(
        {"remind_before_minutes": 15, "lessons": [
            {"id": "a", "title": "A", "weekday": "mon", "start": "09:30"}
        ]},
        default_timezone=MSK,
    )
    assert default.occurrences_on(date(2026, 9, 7))[0].remind_at == datetime(
        2026, 9, 7, 9, 15, tzinfo=MSK
    )


def test_skip_since_and_until_are_respected():
    schedule = build(skip=["2026-09-07"], since="2026-09-01", until="2026-09-30")
    assert schedule.occurrences_on(date(2026, 9, 7)) == []
    assert len(schedule.occurrences_on(date(2026, 9, 14))) == 1
    assert schedule.occurrences_on(date(2026, 10, 5)) == []


def test_parity_alternates_by_study_week():
    schedule = parse_schedule(
        {
            "semester_start": "2026-09-07",
            "lessons": [
                {"id": "odd", "title": "Числитель", "weekday": "mon",
                 "start": "09:30", "parity": "odd"},
                {"id": "even", "title": "Знаменатель", "weekday": "mon",
                 "start": "11:10", "parity": "even"},
            ],
        },
        default_timezone=MSK,
    )
    first_week = schedule.occurrences_on(date(2026, 9, 7))
    second_week = schedule.occurrences_on(date(2026, 9, 14))
    assert [item.lesson.id for item in first_week] == ["odd"]
    assert [item.lesson.id for item in second_week] == ["even"]


def test_study_week_counts_from_semester_start():
    assert study_week(date(2026, 9, 7), date(2026, 9, 7)) == 1
    assert study_week(date(2026, 9, 13), date(2026, 9, 7)) == 1
    assert study_week(date(2026, 9, 14), date(2026, 9, 7)) == 2


def test_one_off_lesson_fires_only_on_its_date():
    schedule = parse_schedule(
        {"lessons": [
            {"id": "kr", "title": "Контрольная", "kind": "test",
             "date": "2026-10-14", "start": "12:10"}
        ]},
        default_timezone=MSK,
    )
    assert len(schedule.occurrences_on(date(2026, 10, 14))) == 1
    assert schedule.occurrences_on(date(2026, 10, 21)) == []


def test_occurrences_are_sorted_by_start_time():
    schedule = parse_schedule(
        {"lessons": [
            {"id": "late", "title": "Вторая", "weekday": "mon", "start": "14:40"},
            {"id": "early", "title": "Первая", "weekday": "mon", "start": "09:30"},
        ]},
        default_timezone=MSK,
    )
    assert [item.lesson.id for item in schedule.occurrences_on(date(2026, 9, 7))] == [
        "early",
        "late",
    ]


def test_occurrence_key_roundtrip():
    schedule = build()
    occurrence = schedule.occurrences_on(date(2026, 9, 7))[0]
    assert occurrence.key == "2026-09-07:matan"
    restored = schedule.occurrence_by_key(occurrence.key)
    assert restored == occurrence


def test_occurrence_by_key_rejects_garbage():
    schedule = build()
    assert schedule.occurrence_by_key("2026-09-07:unknown") is None
    assert schedule.occurrence_by_key("не-дата:matan") is None


def test_upcoming_skips_lessons_that_already_started():
    schedule = build()
    now = datetime(2026, 9, 7, 10, 0, tzinfo=MSK)
    upcoming = schedule.upcoming(now, days=8)
    assert upcoming[0].day == date(2026, 9, 14)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("mon", 0), ("ПН", 0), ("вторник", 1), ("sun", 6), (3, 3), ("4", 4)],
)
def test_parse_weekday_accepts_common_forms(raw, expected):
    assert parse_weekday(raw, "тест") == expected


@pytest.mark.parametrize("raw", ["лекция", "lecture", "ЛК"])
def test_parse_kind_accepts_russian_aliases(raw):
    assert parse_kind(raw, "тест") == "lecture"


@pytest.mark.parametrize(
    ("payload", "message_part"),
    [
        ({"lessons": []}, "нет ни одного занятия"),
        ({"lessons": [{"title": "Без id", "weekday": "mon", "start": "09:30"}]}, "'id'"),
        ({"lessons": [{"id": "a", "weekday": "mon", "start": "09:30"}]}, "'title'"),
        ({"lessons": [{"id": "a", "title": "A", "start": "09:30"}]}, "'weekday'"),
        (
            {"lessons": [{"id": "a", "title": "A", "weekday": "mon",
                          "date": "2026-09-07", "start": "09:30"}]},
            "'weekday'",
        ),
        ({"lessons": [{"id": "a", "title": "A", "weekday": "mon"}]}, "'start'"),
        (
            {"lessons": [{"id": "a", "title": "A", "weekday": "mon",
                          "start": "09:30", "end": "08:00"}]},
            "позже начала",
        ),
        (
            {"lessons": [{"id": "a", "title": "A", "weekday": "mon", "start": "25:00"}]},
            "время",
        ),
        (
            {"lessons": [
                {"id": "same", "title": "A", "weekday": "mon", "start": "09:30"},
                {"id": "same", "title": "B", "weekday": "tue", "start": "09:30"},
            ]},
            "уже используется",
        ),
        (
            {"lessons": [{"id": "плохой id", "title": "A", "weekday": "mon", "start": "09:30"}]},
            "латиницей",
        ),
    ],
)
def test_broken_schedule_reports_readable_error(payload, message_part):
    with pytest.raises(ScheduleError) as error:
        parse_schedule(payload, default_timezone=MSK)
    assert message_part in str(error.value)


def test_missing_file_gives_a_hint():
    with pytest.raises(ScheduleError) as error:
        load_schedule("config/no-such-file.json", default_timezone=MSK)
    assert "не найден" in str(error.value)


def test_example_schedule_is_valid():
    schedule = load_schedule(EXAMPLE, default_timezone=MSK)
    assert schedule.group_name == "БПИ-241"
    assert schedule.timezone == MSK
    assert len(schedule.lessons) == len(json.loads(EXAMPLE.read_text("utf-8"))["lessons"]) + len(
        json.loads(EXAMPLE.read_text("utf-8"))["extra"]
    )
    monday = date(2026, 9, 7)
    titles = [item.lesson.title for item in schedule.occurrences_on(monday)]
    assert titles == ["Математический анализ", "Математический анализ"]
    assert schedule.occurrences_on(date(2026, 10, 14))[0].lesson.kind == "test"


def test_lesson_start_defaults_are_sane():
    schedule = build(end=None)
    occurrence = schedule.occurrences_on(date(2026, 9, 7))[0]
    assert occurrence.end_at is None
    assert occurrence.time_range == "09:30"
    assert occurrence.lesson.start == time(9, 30)
