from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, BufferedInputFile
from telethon import TelegramClient
from telethon.tl.types import Message as TelethonMessage
from telethon.errors import FloodWaitError
from io import BytesIO
import asyncio
import logging

import config
from app.utils.tools import is_admin

router = Router()
logger = logging.getLogger(__name__)


async def retry_on_flood(func, *args, max_retries=3, **kwargs):
    """
    Повторяет вызов функции при FloodWaitError с экспоненциальным ожиданием
    """
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            if attempt < max_retries - 1:
                wait_time = e.seconds if hasattr(e, 'seconds') else 60
                logger.warning(f"FloodWait: ожидание {wait_time} секунд (попытка {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"FloodWait: превышено максимальное количество попыток ({max_retries})")
                raise
        except Exception as e:
            # Другие ошибки не повторяем
            raise


@router.callback_query(F.data.startswith("mod_approve:"))
async def cq_moderation_approve(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Это действие только для администраторов.", show_alert=True)
        return

    telethon_client: TelegramClient = bot.telethon_client
    current_text_for_fallback = callback.message.text or callback.message.caption or "[Сообщение модерации без текста]"

    if not telethon_client or not telethon_client.is_connected():
        await callback.answer("Клиент Telethon не активен.", show_alert=True)
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=f"{current_text_for_fallback}\n\n⚠️ Ошибка: Клиент Telethon не активен.", reply_markup=None)
            elif callback.message.text is not None:
                await callback.message.edit_text(
                    f"{current_text_for_fallback}\n\n⚠️ Ошибка: Клиент Telethon не активен.", reply_markup=None)
            else:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e_edit:
            logger.error(f"MODERATION: Failed to edit message on Telethon client inactive: {e_edit}")
        return

    target_channel_id = config.current_settings.get("target_channel_id")
    if not target_channel_id:
        await callback.answer("Целевой канал не настроен!", show_alert=True)
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=f"{current_text_for_fallback}\n\n⚠️ Ошибка: Целевой канал не настроен.", reply_markup=None)
            elif callback.message.text is not None:
                await callback.message.edit_text(
                    f"{current_text_for_fallback}\n\n⚠️ Ошибка: Целевой канал не настроен.", reply_markup=None)
            else:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e_edit:
            logger.error(f"MODERATION: Failed to edit message on target channel not set: {e_edit}")
        return

    try:
        _, original_chat_id_str, original_message_id_str = callback.data.split(":")
        original_chat_id = int(original_chat_id_str)
        original_message_id = int(original_message_id_str)

        # Удаляем из очереди модерации
        message_key = f"{original_chat_id}:{original_message_id}"
        config.remove_from_moderation_queue(message_key)
    except ValueError:
        await callback.answer("Ошибка в данных колбэка.", show_alert=True)
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=f"{current_text_for_fallback}\n\n⚠️ Ошибка: Неверные данные для модерации.",
                    reply_markup=None)
            elif callback.message.text is not None:
                await callback.message.edit_text(
                    f"{current_text_for_fallback}\n\n⚠️ Ошибка: Неверные данные для модерации.", reply_markup=None)
            else:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e_edit:
            logger.error(f"MODERATION: Failed to edit message on bad callback data: {e_edit}")
        return

    new_status_text = "\n\n✅ Одобрено и отправлено."
    try:
        message_to_copy: TelethonMessage = await telethon_client.get_messages(original_chat_id, ids=original_message_id)

        if not message_to_copy:
            new_status_text = "\n\n❌ Не удалось найти оригинальное сообщение."
            await callback.answer("Оригинальное сообщение не найдено.", show_alert=True)
        else:
            if message_to_copy.grouped_id:
                album_messages = await telethon_client.get_messages(original_chat_id,
                                                                    grouped_id=message_to_copy.grouped_id)
                if album_messages:
                    album_messages.sort(key=lambda m: m.id)
                    files_to_send = [msg_in_album.media for msg_in_album in album_messages if msg_in_album.media]
                    caption_for_album = next((msg.text for msg in album_messages if msg.text), None)
                    if files_to_send:
                        await retry_on_flood(telethon_client.send_file, target_channel_id, file=files_to_send,
                                           caption=caption_for_album)
                    else:
                        await retry_on_flood(telethon_client.send_message, target_channel_id, message=message_to_copy)
                else:
                    await retry_on_flood(telethon_client.send_message, target_channel_id, message=message_to_copy)
            else:
                await retry_on_flood(telethon_client.send_message, target_channel_id, message=message_to_copy)

            await callback.answer("Сообщение одобрено и отправлено.")

    except Exception as e:
        logger.error(f"MODERATION: Error during approval for msg {original_message_id} from {original_chat_id}: {e}",
                     exc_info=True)
        new_status_text = f"\n\n⚠️ Ошибка при одобрении: {e}"
        await callback.answer(f"Ошибка: {e}", show_alert=True)

    try:
        original_caption = callback.message.caption
        original_text = callback.message.text

        if original_caption is not None:
            await callback.message.edit_caption(caption=f"{original_caption}{new_status_text}", reply_markup=None)
        elif original_text is not None:
            await callback.message.edit_text(text=f"{original_text}{new_status_text}", reply_markup=None)
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
            await bot.send_message(callback.message.chat.id, text=new_status_text.strip())
    except Exception as edit_e:
        logger.error(f"MODERATION: Failed to edit moderation message after approval: {edit_e}", exc_info=True)
        await bot.send_message(callback.message.chat.id, text=new_status_text.strip())


@router.callback_query(F.data.startswith("mod_reject:"))
async def cq_moderation_reject(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Это действие только для администраторов.", show_alert=True)
        return

    # Удаляем из очереди модерации
    try:
        _, original_chat_id_str, original_message_id_str = callback.data.split(":")
        message_key = f"{original_chat_id_str}:{original_message_id_str}"
        config.remove_from_moderation_queue(message_key)
    except ValueError:
        pass

    new_status_text = "\n\n❌ Отклонено."
    try:
        original_caption = callback.message.caption
        original_text = callback.message.text

        if original_caption is not None:
            await callback.message.edit_caption(caption=f"{original_caption}{new_status_text}", reply_markup=None)
        elif original_text is not None:
            await callback.message.edit_text(text=f"{original_text}{new_status_text}", reply_markup=None)
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
            await bot.send_message(callback.message.chat.id, text=new_status_text.strip())
        await callback.answer("Сообщение отклонено.")
    except Exception as e:
        logger.error(f"MODERATION: Failed to edit moderation message after rejection: {e}", exc_info=True)
        await callback.answer(f"Ошибка при отклонении: {e}", show_alert=True)
        await bot.send_message(callback.message.chat.id, text=new_status_text.strip())
