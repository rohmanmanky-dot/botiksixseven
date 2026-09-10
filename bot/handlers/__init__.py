"""Роутеры бота."""

from aiogram import Router

from . import admin, attendance, common


def build_router() -> Router:
    """Порядок важен: команды разбираются раньше, чем «+» и «-» в чате."""
    router = Router(name="root")
    router.include_router(common.router)
    router.include_router(admin.router)
    router.include_router(attendance.router)
    return router


__all__ = ["build_router"]
