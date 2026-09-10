"""Хранилище: перекличка, сообщения-переклички, привязка ФИО и id чата."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

STATUSES = ("yes", "no", "late")

STATUS_LABELS = {
    "yes": "✅ буду",
    "no": "❌ не буду",
    "late": "🕐 опоздаю",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS attendance (
    occurrence_key TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    status         TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (occurrence_key, user_id)
);

CREATE TABLE IF NOT EXISTS polls (
    occurrence_key TEXT PRIMARY KEY,
    chat_id        INTEGER NOT NULL,
    message_id     INTEGER NOT NULL,
    closes_at      TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_polls_chat ON polls (chat_id, closes_at);

CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL,
    username   TEXT,
    linked     INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Vote:
    user_id: int
    status: str
    full_name: str
    username: str | None
    updated_at: str

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else self.full_name


class Database:
    """Тонкая обёртка над SQLite — одно соединение на процесс."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База не инициализирована: сначала вызовите connect()")
        return self._conn

    # ---------------------------------------------------------------- users

    async def remember_user(
        self, user_id: int, full_name: str, username: str | None, *, linked: bool = False
    ) -> None:
        """Запоминает пользователя. Ручная привязка (/me) не затирается автоматикой."""
        await self.conn.execute(
            """
            INSERT INTO users (user_id, full_name, username, linked, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name  = CASE WHEN ? OR users.linked = 0
                                  THEN excluded.full_name ELSE users.full_name END,
                username   = excluded.username,
                linked     = MAX(users.linked, excluded.linked),
                updated_at = excluded.updated_at
            """,
            (user_id, full_name, username, int(linked), _now(), int(linked)),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone()

    # ----------------------------------------------------------- attendance

    async def set_vote(self, occurrence_key: str, user_id: int, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        await self.conn.execute(
            """
            INSERT INTO attendance (occurrence_key, user_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(occurrence_key, user_id) DO UPDATE SET
                status = excluded.status, updated_at = excluded.updated_at
            """,
            (occurrence_key, user_id, status, _now()),
        )
        await self.conn.commit()

    async def clear_vote(self, occurrence_key: str, user_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM attendance WHERE occurrence_key = ? AND user_id = ?",
            (occurrence_key, user_id),
        )
        await self.conn.commit()

    async def get_votes(self, occurrence_key: str) -> list[Vote]:
        async with self.conn.execute(
            """
            SELECT a.user_id, a.status, a.updated_at,
                   COALESCE(u.full_name, 'id' || a.user_id) AS full_name,
                   u.username
            FROM attendance a
            LEFT JOIN users u ON u.user_id = a.user_id
            WHERE a.occurrence_key = ?
            ORDER BY a.updated_at
            """,
            (occurrence_key,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Vote(
                user_id=row["user_id"],
                status=row["status"],
                full_name=row["full_name"],
                username=row["username"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def get_votes_for_keys(self, keys: list[str]) -> dict[str, list[Vote]]:
        result: dict[str, list[Vote]] = {}
        for key in keys:
            result[key] = await self.get_votes(key)
        return result

    # ---------------------------------------------------------------- polls

    async def save_poll(
        self, occurrence_key: str, chat_id: int, message_id: int, closes_at: datetime
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO polls (occurrence_key, chat_id, message_id, closes_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(occurrence_key) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                closes_at = excluded.closes_at,
                created_at = excluded.created_at
            """,
            (occurrence_key, chat_id, message_id, closes_at.isoformat(), _now()),
        )
        await self.conn.commit()

    async def get_poll(self, occurrence_key: str) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM polls WHERE occurrence_key = ?", (occurrence_key,)
        ) as cursor:
            return await cursor.fetchone()

    async def latest_open_poll(self, chat_id: int, now: datetime) -> aiosqlite.Row | None:
        """Последняя перекличка в чате, по которой ещё принимаются ответы."""
        async with self.conn.execute(
            """
            SELECT * FROM polls
            WHERE chat_id = ? AND closes_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, now.isoformat()),
        ) as cursor:
            return await cursor.fetchone()

    async def poll_by_message(self, chat_id: int, message_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM polls WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ) as cursor:
            return await cursor.fetchone()

    # ------------------------------------------------------------- settings

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await self.conn.commit()

    async def get_setting(self, key: str) -> str | None:
        async with self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row["value"] if row else None
