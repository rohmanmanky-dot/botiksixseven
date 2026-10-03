"""Команды для всех участников чата."""

from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..keyboards import (
    NAV_PREFIX,
    day_nav_keyboard,
    parse_nav_callback,
    week_nav_keyboard,
    week_start,
)
from ..service import AttendanceService
from ..texts import HELP_TEXT, render_day, render_next, render_week

router = Router(name="common")

MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 80


@router.message(CommandStart())
async def cmd_start(message: Message, service: AttendanceService) -> None:
    group = service.schedule.group_name
    hello = f"Привет! Я бот группы {group} 👋" if group else "Привет! Я бот учебной группы 👋"
    await message.answer(f"{hello}\n\n{HELP_TEXT}", disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, disable_web_page_preview=True)


def day_view(service: AttendanceService, day: date) -> tuple[str, InlineKeyboardMarkup]:
    today = service.now().date()
    text = render_day(day, service.schedule.occurrences_on(day), today=today)
    return text, day_nav_keyboard(day, today)


def week_view(service: AttendanceService, monday: date) -> tuple[str, InlineKeyboardMarkup]:
    today = service.now().date()
    return render_week(service.schedule, monday), week_nav_keyboard(monday, today)


@router.message(Command("today"))
async def cmd_today(message: Message, service: AttendanceService) -> None:
    text, keyboard = day_view(service, service.now().date())
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, service: AttendanceService) -> None:
    text, keyboard = day_view(service, service.now().date() + timedelta(days=1))
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("week"))
async def cmd_week(message: Message, service: AttendanceService) -> None:
    text, keyboard = week_view(service, week_start(service.now().date()))
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{NAV_PREFIX}:"))
async def on_schedule_nav(callback: CallbackQuery, service: AttendanceService) -> None:
    """Листает расписание в том же сообщении, а не плодит новые."""
    parsed = parse_nav_callback(callback.data or "", service.now().date())
    message = callback.message
    if parsed is None or not isinstance(message, Message):
        await callback.answer("Эта кнопка устарела — вызовите /today или /week заново.")
        return

    view, day = parsed
    text, keyboard = day_view(service, day) if view == "day" else week_view(service, day)
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        # Двойной тап по «Сегодня» — текст не изменился, это не ошибка.
        if "message is not modified" not in str(error):
            raise
    await callback.answer()


@router.message(Command("next"))
async def cmd_next(message: Message, service: AttendanceService) -> None:
    now = service.now()
    await message.answer(
        render_next(await service.next_occurrence(now), now), disable_web_page_preview=True
    )


@router.message(Command("me"))
async def cmd_me(message: Message, command: CommandObject, service: AttendanceService) -> None:
    """Привязывает ФИО к аккаунту, чтобы в отчёте были фамилии, а не ники."""
    if message.from_user is None:
        return
    name = (command.args or "").strip()
    if len(name) < MIN_NAME_LENGTH:
        current = await service.db.get_user(message.from_user.id)
        known = f"\n\nСейчас я записал вас как: <b>{current['full_name']}</b>" if current else ""
        await message.answer(
            "Напишите ФИО после команды, например:\n<code>/me Ахмедов Рахман</code>" + known
        )
        return
    if len(name) > MAX_NAME_LENGTH:
        await message.answer("Слишком длинное имя, уложитесь в 80 символов.")
        return

    await service.db.remember_user(
        message.from_user.id, name, message.from_user.username, linked=True
    )
    note = ""
    if service.roster and service.roster.find_by_name(name) is None:
        note = "\n\n⚠️ В списке группы такого ФИО нет — проверьте написание или скажите старосте."
    await message.answer(f"Записал: <b>{name}</b> ✅{note}")


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    if message.from_user is None:
        return
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        f"ID этого чата: <code>{message.chat.id}</code>"
    )
