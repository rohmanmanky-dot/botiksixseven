"""Команды старосты: привязка чата, ручная перекличка, отчёты, выгрузка."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from ..schedule import ScheduleError
from ..scheduler import ReminderScheduler
from ..service import AttendanceService
from ..texts import csv_rows, render_report

log = logging.getLogger(__name__)

router = Router(name="admin")

EXPORT_MAX_DAYS = 90


async def is_staff(message: Message, service: AttendanceService) -> bool:
    """Староста — это ADMIN_IDS из .env либо администратор группы."""
    if message.from_user is None:
        return False
    if service.settings.is_admin(message.from_user.id):
        return True
    if message.chat.type in {"group", "supergroup"}:
        try:
            member = await service.bot.get_chat_member(message.chat.id, message.from_user.id)
        except TelegramBadRequest:
            return False
        return member.status in {"creator", "administrator"}
    return False


async def deny(message: Message) -> None:
    await message.reply("Эта команда только для старосты 🙃")


def parse_day(raw: str | None, today: date) -> date | None:
    """Принимает 'сегодня', 'вчера', 'завтра' или ГГГГ-ММ-ДД."""
    if not raw or not raw.strip():
        return today
    value = raw.strip().lower()
    shortcuts = {
        "сегодня": today,
        "today": today,
        "вчера": today - timedelta(days=1),
        "yesterday": today - timedelta(days=1),
        "завтра": today + timedelta(days=1),
        "tomorrow": today + timedelta(days=1),
    }
    if value in shortcuts:
        return shortcuts[value]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.message(Command("here"))
async def cmd_here(message: Message, service: AttendanceService) -> None:
    if not await is_staff(message, service):
        await deny(message)
        return
    if service.settings.chat_id is not None and service.settings.chat_id != message.chat.id:
        await message.reply(
            "В .env жёстко задан другой CHAT_ID — сначала уберите его оттуда."
        )
        return
    await service.set_target_chat(message.chat.id)
    await message.reply(
        "Готово: буду присылать напоминания и перекличку сюда ✅\n"
        "Дайте мне права закреплять сообщения, чтобы перекличку было видно."
    )


@router.message(Command("ask"))
async def cmd_ask(message: Message, service: AttendanceService) -> None:
    """Запускает перекличку по ближайшей паре, не дожидаясь напоминания."""
    if not await is_staff(message, service):
        await deny(message)
        return
    occurrence = await service.next_occurrence()
    if occurrence is None:
        await message.reply("Ближайших пар в расписании нет.")
        return
    if await service.send_poll(occurrence, chat_id=message.chat.id):
        await service.set_target_chat(message.chat.id)
    else:
        await message.reply("Не получилось отправить перекличку, смотрите логи бота.")


@router.message(Command("report"))
async def cmd_report(
    message: Message, command: CommandObject, service: AttendanceService
) -> None:
    if not await is_staff(message, service):
        await deny(message)
        return
    day = parse_day(command.args, service.now().date())
    if day is None:
        await message.reply("Не понял дату. Формат: <code>/report 2026-09-12</code>")
        return
    items = await service.report_items(day)
    await message.reply(render_report(day, items, service.roster))


@router.message(Command("export"))
async def cmd_export(
    message: Message, command: CommandObject, service: AttendanceService
) -> None:
    """CSV за период: /export (сегодня) или /export 2026-09-01 2026-09-30."""
    if not await is_staff(message, service):
        await deny(message)
        return

    today = service.now().date()
    parts = (command.args or "").split()
    start = parse_day(parts[0] if parts else None, today)
    end = parse_day(parts[1], today) if len(parts) > 1 else start
    if start is None or end is None:
        await message.reply(
            "Формат: <code>/export</code> или <code>/export 2026-09-01 2026-09-30</code>"
        )
        return
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > EXPORT_MAX_DAYS:
        await message.reply(f"Слишком большой период, максимум {EXPORT_MAX_DAYS} дней.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    header_written = False
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        rows = csv_rows(day, await service.report_items(day), service.roster)
        if len(rows) <= 1:
            continue
        writer.writerows(rows if not header_written else rows[1:])
        header_written = True

    if not header_written:
        await message.reply("За этот период отметок нет.")
        return

    # BOM — чтобы Excel не ломал кириллицу.
    payload = ("﻿" + buffer.getvalue()).encode("utf-8")
    filename = f"attendance_{start.isoformat()}_{end.isoformat()}.csv"
    await message.reply_document(
        BufferedInputFile(payload, filename=filename),
        caption=f"Перекличка с {start.isoformat()} по {end.isoformat()}",
    )


@router.message(Command("reload"))
async def cmd_reload(
    message: Message, service: AttendanceService, reminders: ReminderScheduler
) -> None:
    if not await is_staff(message, service):
        await deny(message)
        return
    try:
        schedule = service.reload()
    except (ScheduleError, ValueError) as exc:
        await message.reply(f"Не смог перечитать расписание:\n<code>{exc}</code>")
        return
    planned = await reminders.plan()
    await message.reply(
        f"Расписание перечитано: занятий в файле — {len(schedule.lessons)} ✅\n"
        f"Напоминаний запланировано на ближайшие дни: {planned}"
    )
