"""Настройки бота, читаемые из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Некорректная конфигурация бота."""


def _parse_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS: {chunk!r} не похоже на Telegram ID") from exc
    return ids


def _parse_time(raw: str, name: str) -> time | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ConfigError(f"{name}: ожидается формат ЧЧ:ММ, получено {raw!r}") from exc


def _parse_int(raw: str, name: str, default: int, minimum: int = 0) -> int:
    raw = raw.strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: ожидается число, получено {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name}: значение не может быть меньше {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    token: str
    admin_ids: set[int] = field(default_factory=set)
    chat_id: int | None = None
    timezone: ZoneInfo = ZoneInfo("Europe/Moscow")
    remind_before_minutes: int = 30
    digest_at: time | None = time(8, 0)
    summary_after_minutes: int = 10
    schedule_path: Path = Path("config/schedule.json")
    roster_path: Path = Path("config/roster.json")
    db_path: Path = Path("data/bot.sqlite3")

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    """Собирает настройки из окружения, подхватывая .env, если он есть."""
    if env_file is not None and Path(env_file).exists():
        load_dotenv(env_file)

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и вставьте токен от @BotFather."
        )

    tz_name = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"TIMEZONE: неизвестный часовой пояс {tz_name!r}") from exc

    chat_raw = os.getenv("CHAT_ID", "").strip()
    chat_id: int | None = None
    if chat_raw:
        try:
            chat_id = int(chat_raw)
        except ValueError as exc:
            raise ConfigError(f"CHAT_ID: ожидается число, получено {chat_raw!r}") from exc

    return Settings(
        token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        chat_id=chat_id,
        timezone=timezone,
        remind_before_minutes=_parse_int(
            os.getenv("REMIND_BEFORE_MINUTES", ""), "REMIND_BEFORE_MINUTES", 30
        ),
        digest_at=_parse_time(os.getenv("DIGEST_AT", "08:00"), "DIGEST_AT"),
        summary_after_minutes=_parse_int(
            os.getenv("SUMMARY_AFTER_MINUTES", ""), "SUMMARY_AFTER_MINUTES", 10
        ),
        schedule_path=Path(os.getenv("SCHEDULE_PATH", "config/schedule.json")),
        roster_path=Path(os.getenv("ROSTER_PATH", "config/roster.json")),
        db_path=Path(os.getenv("DB_PATH", "data/bot.sqlite3")),
    )
