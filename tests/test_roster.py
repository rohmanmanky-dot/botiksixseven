"""Тесты списка группы и поиска тех, кто не отметился."""

from __future__ import annotations

import pytest

from bot.roster import Roster, load_roster, normalize_name, parse_roster


def test_parses_plain_list_of_names():
    roster = parse_roster(["Ахмедов Рахман", "Борисова Анна"])
    assert len(roster) == 2
    assert roster.students[0].name == "Ахмедов Рахман"


def test_parses_objects_with_telegram_ids():
    roster = parse_roster({"students": [{"name": "Борисова Анна", "telegram_id": 42}]})
    assert roster.find_by_id(42).name == "Борисова Анна"


def test_name_matching_ignores_case_spaces_and_yo():
    assert normalize_name("  Виноградов   ПЁТР ") == "виноградов петр"
    roster = parse_roster(["Виноградов Пётр"])
    assert roster.find_by_name("виноградов петр") is not None


def test_missing_excludes_those_who_answered_by_name_or_id():
    roster = parse_roster(
        [{"name": "Ахмедов Рахман"}, {"name": "Борисова Анна", "telegram_id": 42},
         {"name": "Гаджиев Ислам"}]
    )
    missing = roster.missing(answered_names={"ахмедов рахман"}, answered_ids={42})
    assert missing == ["Гаджиев Ислам"]


def test_empty_roster_is_falsy_and_never_reports_missing():
    roster = Roster()
    assert not roster
    assert roster.missing(set(), set()) == []


def test_absent_file_gives_empty_roster():
    assert len(load_roster("config/no-such-roster.json")) == 0


def test_example_roster_is_valid():
    roster = load_roster("config/roster.example.json")
    assert len(roster) == 5


@pytest.mark.parametrize("payload", [[{"name": ""}], ["  "], [123]])
def test_broken_roster_raises(payload):
    with pytest.raises(ValueError):
        parse_roster(payload)
