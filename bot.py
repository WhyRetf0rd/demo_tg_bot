import sys
import os

# Добавляем корень проекта в путь поиска модулей
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import settings
from database.db import Database
from handlers.admin import admin_router
from handlers.user import user_router
from utils.channel_notify import verify_channel_access
from utils.reminders import ReminderService


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="menu", description="Открыть меню"),
            BotCommand(command="admin", description="Панель администратора"),
        ]
    )

    dp = Dispatcher()

    db = Database(settings.database_path)
    await db.init()

    # Планировщик напоминаний живет отдельно от хендлеров.
    reminder_service = ReminderService(bot=bot, db=db)
    await reminder_service.start()
    await reminder_service.restore_jobs()

    dp["db"] = db
    dp["settings"] = settings
    dp["reminder_service"] = reminder_service

    dp.include_router(user_router)
    dp.include_router(admin_router)

    ch_info = await verify_channel_access(bot, settings.channel_id)
    if ch_info.startswith("Ошибка"):
        logging.warning("Проверка CHANNEL_ID: %s", ch_info)
    else:
        logging.info("Канал для уведомлений: %s (id=%s)", ch_info, settings.channel_id)

    try:
        await dp.start_polling(bot)
    finally:
        await reminder_service.shutdown()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
