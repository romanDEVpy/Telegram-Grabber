import asyncio
import logging
import sys
import os
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from telethon import TelegramClient, errors as telethon_errors

import config
from app.handlers import common, admin, moderation
from app.telethon_client.listener import start_telethon_listener, stop_telethon_listener

# Настройка логирования в файл и консоль
os.makedirs(config.DATA_DIR, exist_ok=True)
log_file = os.path.join(config.DATA_DIR, 'bot.log')

# Создаем форматтер
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Обработчик для файла с ротацией (максимум 5 файлов по 5 МБ)
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Обработчик для консоли
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# Настраиваем корневой логгер
logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)

telethon_client = TelegramClient(
    os.path.join(config.DATA_DIR, 'telegrabber_user_session'),
    int(config.API_ID),
    config.API_HASH
)
telethon_run_task = None


async def initialize_telethon_client(aiogram_bot_instance: Bot):
    global telethon_run_task
    try:
        logger.info("Попытка подключения Telethon клиента...")
        os.makedirs(config.DATA_DIR, exist_ok=True)

        if not telethon_client.is_connected():
            if config.PHONE_NUMBER:
                await telethon_client.start(phone=config.PHONE_NUMBER)
            else:
                await telethon_client.start()

        logger.info("Telethon клиент успешно подключен и авторизован.")
        await restart_telethon_handlers(aiogram_bot_instance)


    except telethon_errors.PhoneNumberInvalidError:
        logger.error("Ошибка Telethon: Неверный формат номера телефона. Проверьте .env или введите корректно.")
        sys.exit(1)
    except telethon_errors.SessionPasswordNeededError:
        logger.error("Ошибка Telethon: Требуется пароль двухфакторной аутентификации (2FA). Введите в консоли.")
    except Exception as e:
        logger.error(f"Не удалось инициализировать Telethon клиент: {e}")


async def shutdown_telethon_client():
    global telethon_run_task
    if telethon_client.is_connected():
        logger.info("Отключение Telethon клиента...")
        await stop_telethon_listener(telethon_client)

        if telethon_run_task and not telethon_run_task.done():
            telethon_run_task.cancel()
            try:
                await telethon_run_task
            except asyncio.CancelledError:
                logger.info("Задача run_until_disconnected Telethon клиента отменена.")

        await telethon_client.disconnect()
        logger.info("Telethon клиент отключен.")


async def restart_telethon_handlers(bot_instance: Bot):
    if not telethon_client.is_connected():
        logger.warning("Попытка перезапуска слушателя Telethon, но клиент не подключен.")
        await initialize_telethon_client(bot_instance)
        if not telethon_client.is_connected():
            logger.error("Не удалось подключить Telethon клиент для перезапуска слушателя.")
            return

    logger.info("Перезапуск/настройка обработчиков Telethon...")
    await start_telethon_listener(telethon_client, bot_instance)


async def monitor_telethon_connection(bot_instance: Bot):
    """Мониторит состояние Telethon клиента и перезапускает при необходимости"""
    global telethon_run_task

    while True:
        try:
            await asyncio.sleep(60)  # Проверка каждые 60 секунд

            # Проверяем, подключен ли клиент
            if not telethon_client.is_connected():
                logger.warning("Telethon клиент отключен. Попытка переподключения...")
                try:
                    await initialize_telethon_client(bot_instance)
                    if telethon_client.is_connected() and (not telethon_run_task or telethon_run_task.done()):
                        telethon_run_task = asyncio.create_task(telethon_client.run_until_disconnected())
                        logger.info("Telethon клиент успешно переподключен и перезапущен.")
                except Exception as e:
                    logger.error(f"Ошибка при переподключении Telethon: {e}", exc_info=True)

            # Проверяем, работает ли задача run_until_disconnected
            elif telethon_run_task and telethon_run_task.done():
                logger.warning("Задача run_until_disconnected завершилась. Перезапуск...")
                try:
                    telethon_run_task = asyncio.create_task(telethon_client.run_until_disconnected())
                    logger.info("Задача run_until_disconnected перезапущена.")
                except Exception as e:
                    logger.error(f"Ошибка при перезапуске run_until_disconnected: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Мониторинг Telethon остановлен.")
            break
        except Exception as e:
            logger.error(f"Ошибка в мониторинге Telethon: {e}", exc_info=True)


async def main():
    global telethon_run_task

    config.load_settings()

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не найден. Пожалуйста, установите его в .env файле.")
        return
    if not config.API_ID or not config.API_HASH:
        logger.error("API_ID или API_HASH не найдены. Пожалуйста, установите их в .env файле.")
        return
    if not config.ADMIN_IDS:
        logger.warning("ADMIN_IDS не установлены в .env. Функции администрирования могут быть ограничены.")

    default_bot_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(token=config.BOT_TOKEN, default=default_bot_properties)

    setattr(bot, 'telethon_client', telethon_client)
    setattr(bot, 'restart_telethon_listener', lambda: restart_telethon_handlers(bot))

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)  # dp здесь является экземпляром Dispatcher

    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(moderation.router)

    # VVV ИЗМЕНЕНИЕ СИГНАТУРЫ ЗДЕСЬ VVV
    async def on_startup(bot: Bot):  # Принимаем bot напрямую
        global telethon_run_task
        logger.info("Бот Aiogram запускается...")
        await initialize_telethon_client(bot)  # Используем переданный bot

        if telethon_client.is_connected() and (not telethon_run_task or telethon_run_task.done()):
            telethon_run_task = asyncio.create_task(telethon_client.run_until_disconnected())
            logger.info("Telethon run_until_disconnected запущен в фоновой задаче.")
        elif not telethon_client.is_connected():
            logger.warning("Telethon клиент не был подключен на этапе startup, run_until_disconnected не запущен.")

        # Запускаем мониторинг Telethon соединения
        asyncio.create_task(monitor_telethon_connection(bot))
        logger.info("Мониторинг Telethon соединения запущен.")

    # VVV ИЗМЕНЕНИЕ СИГНАТУРЫ ЗДЕСЬ (для консистентности) VVV
    async def on_shutdown(bot: Bot):  # Принимаем bot, хотя можем не использовать для всех действий
        logger.info("Бот Aiogram останавливается...")
        await shutdown_telethon_client()
        await dp.storage.close()  # Используем dp из внешней области видимости main()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Запуск опроса Aiogram...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.critical(f"Ошибка при запуске Aiogram polling: {e}", exc_info=True)
    finally:
        if telethon_client.is_connected():
            await shutdown_telethon_client()
        logger.info("Бот Aiogram полностью остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Программа прервана пользователем.")
    except Exception as e:
        logger.critical(f"Критическая ошибка в asyncio.run: {e}", exc_info=True)
