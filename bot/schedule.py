"""Разбор расписания группы и вычисление занятий на конкретный день."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "mon": 0, "пн": 0, "понедельник": 0,
    "tue": 1, "вт": 1, "вторник": 1,
    "wed": 2, "ср": 2, "среда": 2,
    "thu": 3, "чт": 3, "четверг": 3,
    "fri": 4, "пт": 4, "пятница": 4,
    "sat": 5, "сб": 5, "суббота": 5,
    "sun": 6, "вс": 6, "воскресенье": 6,
}

WEEKDAY_NAMES = [
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
]

KIND_TITLES = {
    "lecture": "Лекция",
    "seminar": "Семинар",
    "practice": "Практика",
    "lab": "Лабораторная",
    "exam": "Экзамен",
    "test": "Контрольная",
    "other": "Занятие",
}

KIND_EMOJI = {
    "lecture": "📘",
    "seminar": "📝",
    "practice": "🛠",
    "lab": "🔬",
    "exam": "🎓",
    "test": "🧾",
    "other": "📌",
}

KIND_ALIASES = {
    "лекция": "lecture", "лек": "lecture", "лк": "lecture",
    "семинар": "seminar", "сем": "seminar", "см": "seminar",
    "практика": "practice", "прак": "practice",
    "лаба": "lab", "лабораторная": "lab",
    "экзамен": "exam", "зачёт": "exam", "зачет": "exam",
    "контрольная": "test", "кр": "test",
}

ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,24}$")
MAX_REMIND_BEFORE = 24 * 60


class ScheduleError(ValueError):
    """Ошибка в файле расписания."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScheduleError(message)


def parse_weekday(raw: object, where: str) -> int:
    if isinstance(raw, bool):
        raise ScheduleError(f"{where}: день недели указан некорректно")
    if isinstance(raw, int):
        _require(0 <= raw <= 6, f"{where}: день недели должен быть от 0 (пн) до 6 (вс)")
        return raw
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key.isdigit():
            return parse_weekday(int(key), where)
        _require(key in WEEKDAYS, f"{where}: непонятный день недели {raw!r}")
        return WEEKDAYS[key]
    raise ScheduleError(f"{where}: день недели должен быть строкой или числом")


def parse_time(raw: object, where: str) -> time:
    _require(isinstance(raw, str), f"{where}: время должно быть строкой вида '09:30'")
    assert isinstance(raw, str)
    try:
        hours, minutes = raw.strip().split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ScheduleError(f"{where}: непонятное время {raw!r}, нужен формат ЧЧ:ММ") from exc


def parse_date(raw: object, where: str) -> date:
    _require(isinstance(raw, str), f"{where}: дата должна быть строкой вида '2026-09-01'")
    assert isinstance(raw, str)
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ScheduleError(f"{where}: непонятная дата {raw!r}, нужен формат ГГГГ-ММ-ДД") from exc


def parse_kind(raw: object, where: str) -> str:
    if raw is None:
        return "other"
    _require(isinstance(raw, str), f"{where}: тип занятия должен быть строкой")
    assert isinstance(raw, str)
    key = raw.strip().lower()
    key = KIND_ALIASES.get(key, key)
    _require(
        key in KIND_TITLES,
        f"{where}: неизвестный тип занятия {raw!r}. Доступны: {', '.join(sorted(KIND_TITLES))}",
    )
    return key


def study_week(day: date, semester_start: date | None) -> int:
    """Номер учебной недели: от начала семестра, иначе — номер недели по ISO."""
    if semester_start is None:
        return day.isocalendar().week
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    current_monday = day - timedelta(days=day.weekday())
    return (current_monday - first_monday).days // 7 + 1


@dataclass(frozen=True)
class Lesson:
    """Пара в расписании: еженедельная или разовая (если задана `on_date`)."""

    id: str
    title: str
    kind: str = "other"
    weekday: int | None = None
    on_date: date | None = None
    start: time = time(9, 0)
    end: time | None = None
    teacher: str | None = None
    location: str | None = None
    link: str | None = None
    parity: str = "all"
    since: date | None = None
    until: date | None = None
    skip: frozenset[date] = frozenset()
    remind_before_minutes: int | None = None
    note: str | None = None

    @property
    def kind_title(self) -> str:
        return KIND_TITLES.get(self.kind, KIND_TITLES["other"])

    @property
    def emoji(self) -> str:
        return KIND_EMOJI.get(self.kind, KIND_EMOJI["other"])

    def happens_on(self, day: date, semester_start: date | None) -> bool:
        if self.on_date is not None:
            return self.on_date == day
        if day in self.skip:
            return False
        if self.since is not None and day < self.since:
            return False
        if self.until is not None and day > self.until:
            return False
        if self.weekday is None or day.weekday() != self.weekday:
            return False
        if self.parity == "all":
            return True
        week = study_week(day, semester_start)
        return (week % 2 == 1) if self.parity == "odd" else (week % 2 == 0)


@dataclass(frozen=True)
class Occurrence:
    """Конкретное занятие в конкретный день."""

    lesson: Lesson
    day: date
    start_at: datetime
    end_at: datetime | None
    remind_at: datetime

    @property
    def key(self) -> str:
        """Ключ занятия — им склеиваются перекличка, сообщение и кнопки."""
        return f"{self.day.isoformat()}:{self.lesson.id}"

    @property
    def time_range(self) -> str:
        if self.lesson.end is None:
            return self.lesson.start.strftime("%H:%M")
        return f"{self.lesson.start:%H:%M}–{self.lesson.end:%H:%M}"


@dataclass(frozen=True)
class Schedule:
    lessons: tuple[Lesson, ...]
    timezone: ZoneInfo
    default_remind_before_minutes: int = 30
    semester_start: date | None = None
    group_name: str | None = None
    source: Path | None = None

    def lesson_by_id(self, lesson_id: str) -> Lesson | None:
        return next((lesson for lesson in self.lessons if lesson.id == lesson_id), None)

    def occurrences_on(self, day: date) -> list[Occurrence]:
        found = [
            self._build_occurrence(lesson, day)
            for lesson in self.lessons
            if lesson.happens_on(day, self.semester_start)
        ]
        return sorted(found, key=lambda item: item.start_at)

    def occurrence_by_key(self, key: str) -> Occurrence | None:
        day_raw, _, lesson_id = key.partition(":")
        lesson = self.lesson_by_id(lesson_id)
        if lesson is None:
            return None
        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            return None
        return self._build_occurrence(lesson, day)

    def upcoming(self, now: datetime, days: int = 14) -> list[Occurrence]:
        """Занятия, которые ещё не начались, на ближайшие `days` дней."""
        result: list[Occurrence] = []
        for offset in range(days + 1):
            for occurrence in self.occurrences_on(now.date() + timedelta(days=offset)):
                if occurrence.start_at > now:
                    result.append(occurrence)
        return result

    def _build_occurrence(self, lesson: Lesson, day: date) -> Occurrence:
        start_at = datetime.combine(day, lesson.start, tzinfo=self.timezone)
        end_at = (
            datetime.combine(day, lesson.end, tzinfo=self.timezone)
            if lesson.end is not None
            else None
        )
        before = lesson.remind_before_minutes
        if before is None:
            before = self.default_remind_before_minutes
        return Occurrence(
            lesson=lesson,
            day=day,
            start_at=start_at,
            end_at=end_at,
            remind_at=start_at - timedelta(minutes=before),
        )


def _parse_lesson(raw: object, index: int, seen_ids: set[str]) -> Lesson:
    where = f"занятие #{index + 1}"
    _require(isinstance(raw, dict), f"{where}: должно быть объектом JSON")
    assert isinstance(raw, dict)

    title = str(raw.get("title", "")).strip()
    _require(bool(title), f"{where}: не заполнено поле 'title' (название предмета)")
    where = f"занятие {title!r}"

    lesson_id = str(raw.get("id", "")).strip()
    _require(bool(lesson_id), f"{where}: не заполнено поле 'id'")
    _require(
        bool(ID_RE.match(lesson_id)),
        f"{where}: 'id' должен быть латиницей/цифрами/дефисом, до 24 символов",
    )
    _require(lesson_id not in seen_ids, f"{where}: 'id' {lesson_id!r} уже используется")
    seen_ids.add(lesson_id)

    on_date = parse_date(raw["date"], where) if raw.get("date") is not None else None
    weekday = parse_weekday(raw["weekday"], where) if raw.get("weekday") is not None else None
    _require(
        (on_date is None) != (weekday is None),
        f"{where}: укажите либо 'weekday' (еженедельно), либо 'date' (разовое занятие)",
    )

    _require("start" in raw, f"{where}: не указано время начала 'start'")
    start = parse_time(raw["start"], where)
    end = parse_time(raw["end"], where) if raw.get("end") is not None else None
    _require(end is None or end > start, f"{where}: время окончания должно быть позже начала")

    parity = str(raw.get("parity", "all")).strip().lower()
    parity = {"нечетная": "odd", "нечётная": "odd", "числитель": "odd",
              "четная": "even", "чётная": "even", "знаменатель": "even",
              "каждую": "all", "всегда": "all"}.get(parity, parity)
    _require(
        parity in {"all", "odd", "even"},
        f"{where}: 'parity' может быть 'all', 'odd' или 'even'",
    )

    remind_before = raw.get("remind_before_minutes")
    if remind_before is not None:
        _require(
            isinstance(remind_before, int) and not isinstance(remind_before, bool),
            f"{where}: 'remind_before_minutes' должно быть числом",
        )
        assert isinstance(remind_before, int)
        _require(
            0 <= remind_before <= MAX_REMIND_BEFORE,
            f"{where}: 'remind_before_minutes' должно быть от 0 до {MAX_REMIND_BEFORE}",
        )

    skip_raw = raw.get("skip") or []
    _require(isinstance(skip_raw, list), f"{where}: 'skip' должно быть списком дат")
    assert isinstance(skip_raw, list)

    def _clean(field_name: str) -> str | None:
        value = raw.get(field_name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    return Lesson(
        id=lesson_id,
        title=title,
        kind=parse_kind(raw.get("kind"), where),
        weekday=weekday,
        on_date=on_date,
        start=start,
        end=end,
        teacher=_clean("teacher"),
        location=_clean("location"),
        link=_clean("link"),
        parity=parity,
        since=parse_date(raw["since"], where) if raw.get("since") is not None else None,
        until=parse_date(raw["until"], where) if raw.get("until") is not None else None,
        skip=frozenset(parse_date(item, where) for item in skip_raw),
        remind_before_minutes=remind_before,
        note=_clean("note"),
    )


def parse_schedule(
    data: object,
    *,
    default_timezone: ZoneInfo,
    default_remind_before_minutes: int = 30,
    source: Path | None = None,
) -> Schedule:
    _require(isinstance(data, dict), "Расписание должно быть объектом JSON")
    assert isinstance(data, dict)

    raw_lessons = list(data.get("lessons") or [])
    raw_lessons.extend(data.get("extra") or [])
    _require(bool(raw_lessons), "В расписании нет ни одного занятия (список 'lessons' пуст)")

    seen_ids: set[str] = set()
    lessons = tuple(
        _parse_lesson(raw, index, seen_ids) for index, raw in enumerate(raw_lessons)
    )

    timezone = default_timezone
    if data.get("timezone"):
        timezone = ZoneInfo(str(data["timezone"]))

    remind_before = data.get("remind_before_minutes")
    if remind_before is None:
        remind_before = default_remind_before_minutes
    _require(
        isinstance(remind_before, int) and not isinstance(remind_before, bool),
        "'remind_before_minutes' в расписании должно быть числом",
    )
    assert isinstance(remind_before, int)

    semester_start = (
        parse_date(data["semester_start"], "semester_start")
        if data.get("semester_start") is not None
        else None
    )
    group_name = str(data["group"]).strip() if data.get("group") else None

    return Schedule(
        lessons=lessons,
        timezone=timezone,
        default_remind_before_minutes=remind_before,
        semester_start=semester_start,
        group_name=group_name,
        source=source,
    )


def load_schedule(
    path: str | Path,
    *,
    default_timezone: ZoneInfo,
    default_remind_before_minutes: int = 30,
) -> Schedule:
    path = Path(path)
    if not path.exists():
        raise ScheduleError(
            f"Файл расписания не найден: {path}. "
            "Скопируйте config/schedule.example.json и заполните своим расписанием."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"{path}: некорректный JSON — {exc}") from exc
    return parse_schedule(
        data,
        default_timezone=default_timezone,
        default_remind_before_minutes=default_remind_before_minutes,
        source=path,
    )


@dataclass
class ScheduleHolder:
    """Держатель расписания, чтобы /reload подхватывал изменения без перезапуска."""

    schedule: Schedule
    path: Path
    default_remind_before_minutes: int = 30

    def reload(self) -> Schedule:
        self.schedule = load_schedule(
            self.path,
            default_timezone=self.schedule.timezone,
            default_remind_before_minutes=self.default_remind_before_minutes,
        )
        return self.schedule
