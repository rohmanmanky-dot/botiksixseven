"""Список группы: нужен, чтобы староста видел, кто ещё не отметился."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Приводит ФИО к сравнимому виду: без лишних пробелов, ё → е, нижний регистр."""
    return _SPACES.sub(" ", name.strip().lower()).replace("ё", "е")


@dataclass(frozen=True)
class Student:
    name: str
    telegram_id: int | None = None

    @property
    def key(self) -> str:
        return normalize_name(self.name)


@dataclass(frozen=True)
class Roster:
    students: tuple[Student, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.students)

    def __len__(self) -> int:
        return len(self.students)

    def find_by_name(self, name: str) -> Student | None:
        key = normalize_name(name)
        return next((student for student in self.students if student.key == key), None)

    def find_by_id(self, telegram_id: int) -> Student | None:
        return next(
            (student for student in self.students if student.telegram_id == telegram_id), None
        )

    def missing(self, answered_names: set[str], answered_ids: set[int]) -> list[str]:
        """ФИО тех, кто ещё не ответил ни кнопкой, ни плюсом."""
        answered_keys = {normalize_name(name) for name in answered_names}
        return [
            student.name
            for student in self.students
            if student.key not in answered_keys
            and (student.telegram_id is None or student.telegram_id not in answered_ids)
        ]


def parse_roster(data: object) -> Roster:
    """Принимает как список строк, так и {'students': [...]} с объектами."""
    if isinstance(data, dict):
        data = data.get("students", [])
    if not isinstance(data, list):
        raise ValueError("Список группы должен быть массивом ФИО или объектов")

    students: list[Student] = []
    for item in data:
        if isinstance(item, str):
            name = item.strip()
            telegram_id = None
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            raw_id = item.get("telegram_id")
            telegram_id = int(raw_id) if raw_id not in (None, "") else None
        else:
            raise ValueError(f"Непонятная запись в списке группы: {item!r}")
        if not name:
            raise ValueError("В списке группы есть запись без ФИО")
        students.append(Student(name=name, telegram_id=telegram_id))
    return Roster(students=tuple(students))


def load_roster(path: str | Path) -> Roster:
    """Список группы необязателен: если файла нет — работаем без него."""
    path = Path(path)
    if not path.exists():
        return Roster()
    return parse_roster(json.loads(path.read_text(encoding="utf-8")))
