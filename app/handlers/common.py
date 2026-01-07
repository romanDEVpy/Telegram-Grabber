from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient

import config
from app.keyboards.inline import main_admin_keyboard
from app.utils.tools import is_admin

router = Router()


async def get_target_channel_title(bot_instance: Bot) -> str | None:
    target_id = config.current_settings.get("target_channel_id")
    if target_id:
        telethon_client: TelegramClient = bot_instance.telethon_client
        try:
            entity = await telethon_client.get_entity(target_id)
            return getattr(entity, 'title', str(target_id))
        except Exception:
            return str(target_id)  # Fallback to ID if title fetch fails
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not is_admin(message, config.ADMIN_IDS):
        await message.answer("Привет! Этот бот для администрирования копирования новостей. "
                             "Если ты администратор, используй команду /admin.")
        return
    target_title = await get_target_channel_title(bot)
    await message.answer(
        "Добро пожаловать в панель администратора!",
        reply_markup=main_admin_keyboard(
            config.current_settings["premoderation_enabled"],
            config.current_settings["target_channel_id"],
            target_title
        )
    )


@router.message(Command("admin"))
async def cmd_admin_panel(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not is_admin(message, config.ADMIN_IDS):
        await message.answer("Доступ запрещен. Эта команда только для администраторов.")
        return
    target_title = await get_target_channel_title(bot)
    await message.answer(
        "Панель администратора:",
        reply_markup=main_admin_keyboard(
            config.current_settings["premoderation_enabled"],
            config.current_settings["target_channel_id"],
            target_title
        )
    )


@router.callback_query(F.data == "admin_panel")
async def cq_admin_panel(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    target_title = await get_target_channel_title(bot)
    try:
        await callback.message.edit_text(
            "Панель администратора:",
            reply_markup=main_admin_keyboard(
                config.current_settings["premoderation_enabled"],
                config.current_settings["target_channel_id"],
                target_title
            )
        )
    except Exception as e:
        print(f"Error editing message for admin_panel: {e}")
        await callback.message.answer(
            "Панель администратора:",
            reply_markup=main_admin_keyboard(
                config.current_settings["premoderation_enabled"],
                config.current_settings["target_channel_id"],
                target_title
            )
        )
    await callback.answer()


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "Этот бот копирует сообщения из одних каналов в другой.\n"
        "Доступные команды:\n"
        "/start - Начало работы\n"
        "/admin - Панель администратора (только для админов)\n"
        "/help - Это сообщение\n\n"
        "Настройки в панели администратора:\n"
        "- Добавить/удалить источник\n"
        "- Установить целевой канал\n"
        "- Включить/выключить предмодерацию\n"
        "- Просмотреть список источников"
    )
    await message.answer(help_text)
