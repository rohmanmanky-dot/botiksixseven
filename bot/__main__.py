"""Точка входа: python -m bot"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import ConfigError, load_settings
from .db import Database
from .handlers import build_router
from .roster import load_roster
from .schedule import ScheduleError, ScheduleHolder, load_schedule
from .scheduler import ReminderScheduler
from .service import AttendanceService

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="today", description="Расписание на сегодня"),
    BotCommand(command="tomorrow", description="Расписание на завтра"),
    BotCommand(command="week", description="Расписание на неделю"),
    BotCommand(command="next", description="Ближайшая пара"),
    BotCommand(command="me", description="Представиться: /me Иванов Иван"),
    BotCommand(command="ask", description="Староста: начать перекличку"),
    BotCommand(command="report", description="Староста: отчёт за день"),
    BotCommand(command="export", description="Староста: выгрузка в CSV"),
    BotCommand(command="help", description="Что я умею"),
]


async def run() -> None:
    settings = load_settings()

    schedule = load_schedule(
        settings.schedule_path,
        default_timezone=settings.timezone,
        default_remind_before_minutes=settings.remind_before_minutes,
    )
    holder = ScheduleHolder(
        schedule=schedule,
        path=settings.schedule_path,
        default_remind_before_minutes=settings.remind_before_minutes,
    )
    roster = load_roster(settings.roster_path)
    log.info(
        "Расписание: %s занятий, список группы: %s человек",
        len(schedule.lessons),
        len(roster),
    )

    database = Database(settings.db_path)
    await database.connect()

    bot = Bot(
        token=settings.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    service = AttendanceService(bot, database, holder, settings, roster)
    reminders = ReminderScheduler(service, settings)

    dispatcher = Dispatcher()
    dispatcher["service"] = service
    dispatcher["reminders"] = reminders
    dispatcher.include_router(build_router())

    await reminders.start()
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Бот запущен")
        await dispatcher.start_polling(bot)
    finally:
        reminders.shutdown()
        await database.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except (ConfigError, ScheduleError) as exc:
        raise SystemExit(f"Ошибка конфигурации: {exc}") from exc
    except KeyboardInterrupt:
        log.info("Остановлено вручную")


if __name__ == "__main__":
    main()
