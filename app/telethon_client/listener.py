import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import Message as TelethonMessage
from telethon.errors import FloodWaitError
from aiogram import Bot as AiogramBot
from aiogram.types import BufferedInputFile
from io import BytesIO
import logging

import config
from app.keyboards.inline import moderation_keyboard

logger = logging.getLogger(__name__)
listener_task = None


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


async def handle_new_message(event: events.NewMessage.Event, aiogram_bot_instance: AiogramBot,
                             telethon_client_instance: TelegramClient):
    message: TelethonMessage = event.message
    raw_source_id = event.chat_id

    # Используем унифицированную функцию нормализации ID
    normalized_source_id_str = config.normalize_channel_id(raw_source_id)

    logger.info(f"LISTENER: Raw event.chat_id: {raw_source_id}")
    logger.info(f"LISTENER: Normalized source_id_str for matching: {normalized_source_id_str}")
    logger.info(f"LISTENER: Current source_channels config: {config.current_settings['source_channels']}")
    logger.info(f"LISTENER: Current target_channel_id config: {config.current_settings.get('target_channel_id')}")
    logger.info(
        f"LISTENER: Current premoderation_enabled config: {config.current_settings.get('premoderation_enabled')}")

    if normalized_source_id_str not in config.current_settings["source_channels"]:
        logger.info(
            f"LISTENER: Normalized Source ID {normalized_source_id_str} not found in tracked source_channels keys {list(config.current_settings['source_channels'].keys())}. Ignoring message.")
        return

    logger.info(f"LISTENER: Normalized Source ID {normalized_source_id_str} IS IN tracked list. Processing...")

    kbd = moderation_keyboard(original_message_id=message.id, original_chat_id=raw_source_id)
    target_channel_id = config.current_settings.get("target_channel_id")
    premoderation_enabled = config.current_settings.get("premoderation_enabled", True)
    moderation_destination_chat_id = config.current_settings.get("moderation_chat_id")

    if not moderation_destination_chat_id and config.ADMIN_IDS:
        moderation_destination_chat_id = config.ADMIN_IDS[0]

    if not target_channel_id and not premoderation_enabled:
        logger.warning(
            f"LISTENER: Target channel not configured and premoderation is OFF. Cannot process message from {raw_source_id}.")
        return

    if premoderation_enabled:
        if not moderation_destination_chat_id:
            logger.warning(
                f"LISTENER: Premoderation is ON, but moderation_chat_id (or ADMIN_IDS) not set. Message from {raw_source_id} will not be sent for moderation.")
            return
        try:
            logger.info(f"LISTENER: Premoderation ON. Preparing message for admin {moderation_destination_chat_id}.")
            sender_entity = await telethon_client_instance.get_entity(raw_source_id)
            sender_title = getattr(sender_entity, 'title', getattr(sender_entity, 'username', f"ID: {raw_source_id}"))

            moderation_text = f"🔔 Новый пост из: **{sender_title}** (<code>{raw_source_id}</code>)\n"
            moderation_text += f"Message ID: <code>{message.id}</code>\n\n"

            max_caption_len = 1024
            visible_text_len = max_caption_len - len(moderation_text) - 20

            if message.text:
                moderation_text += message.text[:visible_text_len] + (
                    '...' if len(message.text) > visible_text_len else '')

            if message.media:
                logger.info(
                    f"LISTENER: Message from {raw_source_id} has media. Attempting to download for moderation preview.")
                downloaded_media = None
                try:
                    actual_message_to_preview = message
                    is_album_text_addition = ""
                    if message.grouped_id:
                        is_album_text_addition = "\n\n🖼️ _Это сообщение является частью альбома._"
                        album_messages = await telethon_client_instance.get_messages(raw_source_id,
                                                                                     grouped_id=message.grouped_id)
                        if album_messages:
                            album_messages.sort(key=lambda m: m.id)
                            actual_message_to_preview = album_messages[0]
                        if not actual_message_to_preview.media:
                            actual_message_to_preview = message

                    moderation_text_with_album_note = moderation_text + is_album_text_addition

                    if actual_message_to_preview.photo:
                        downloaded_media = await actual_message_to_preview.download_media(file=BytesIO())
                        downloaded_media.seek(0)
                        input_file = BufferedInputFile(downloaded_media.read(), filename="photo.jpg")
                        await retry_on_flood(
                            aiogram_bot_instance.send_photo, moderation_destination_chat_id, input_file,
                            caption=moderation_text_with_album_note, reply_markup=kbd, parse_mode="HTML"
                        )
                    elif actual_message_to_preview.video:
                        downloaded_media = await actual_message_to_preview.download_media(file=BytesIO())
                        downloaded_media.seek(0)
                        input_file = BufferedInputFile(downloaded_media.read(), filename="video.mp4")
                        await retry_on_flood(
                            aiogram_bot_instance.send_video, moderation_destination_chat_id, input_file,
                            caption=moderation_text_with_album_note, reply_markup=kbd, parse_mode="HTML"
                        )
                    else:
                        if not message.text:
                            moderation_text_with_album_note += "\n\n[Медиа контент без текста (тип не для предпросмотра)]"
                        else:
                            moderation_text_with_album_note += "\n\n[Медиа контент (тип не для предпросмотра)]"
                        await retry_on_flood(
                            aiogram_bot_instance.send_message, moderation_destination_chat_id,
                            moderation_text_with_album_note, reply_markup=kbd,
                            parse_mode="HTML", disable_web_page_preview=True
                        )

                except Exception as e_media:
                    logger.error(
                        f"LISTENER: Error downloading/sending media for moderation from {raw_source_id}: {e_media}",
                        exc_info=True)
                    moderation_text += "\n\n⚠️ _Не удалось загрузить предпросмотр медиа._"
                    await retry_on_flood(
                        aiogram_bot_instance.send_message, moderation_destination_chat_id, moderation_text,
                        reply_markup=kbd, parse_mode="HTML", disable_web_page_preview=True
                    )
                finally:
                    if downloaded_media and hasattr(downloaded_media, 'close'):
                        downloaded_media.close()
            else:
                await retry_on_flood(
                    aiogram_bot_instance.send_message, moderation_destination_chat_id, moderation_text,
                    reply_markup=kbd, parse_mode="HTML", disable_web_page_preview=True
                )

            logger.info(
                f"LISTENER: Message from {raw_source_id} (msg_id: {message.id}) sent for moderation to {moderation_destination_chat_id}.")

            # Сохраняем сообщение в очередь модерации
            message_key = f"{raw_source_id}:{message.id}"
            config.add_to_moderation_queue(message_key, raw_source_id, message.id)

        except Exception as e:
            logger.error(f"LISTENER: Error preparing/sending message for moderation from {raw_source_id}: {e}",
                         exc_info=True)
            if moderation_destination_chat_id:
                try:
                    await aiogram_bot_instance.send_message(moderation_destination_chat_id,
                                                            f"⚠️ Ошибка обработки сообщения из {raw_source_id} для модерации: {e}")
                except Exception as admin_notify_e:
                    logger.error(f"LISTENER: Failed to notify admin about moderation error: {admin_notify_e}",
                                 exc_info=True)

    else:
        logger.info(f"LISTENER: Premoderation OFF. Attempting direct copy from {raw_source_id} to {target_channel_id}.")
        if not target_channel_id:
            logger.warning(
                f"LISTENER: Premoderation OFF, but target_channel_id not set for source {raw_source_id}. Cannot copy.")
            return
        try:
            if message.grouped_id:
                logger.info(
                    f"LISTENER: Message from {raw_source_id} is part of an album (grouped_id: {message.grouped_id}). Fetching album.")
                album_messages = await telethon_client_instance.get_messages(raw_source_id,
                                                                             grouped_id=message.grouped_id)
                if not album_messages:
                    logger.warning(
                        f"LISTENER: Could not fetch album messages for grouped_id {message.grouped_id} from {raw_source_id}. Sending original trigger message instead.")
                    await retry_on_flood(telethon_client_instance.send_message, target_channel_id, message=message)
                else:
                    album_messages.sort(key=lambda m: m.id)
                    files_to_send = []
                    caption_for_album = None
                    for i, msg_in_album in enumerate(album_messages):
                        if msg_in_album.media:
                            files_to_send.append(msg_in_album.media)
                            if i == 0 and msg_in_album.text:
                                caption_for_album = msg_in_album.text

                    if files_to_send:
                        logger.info(
                            f"LISTENER: Sending album with {len(files_to_send)} media items from {raw_source_id} to {target_channel_id}.")
                        await retry_on_flood(
                            telethon_client_instance.send_file, target_channel_id, file=files_to_send,
                            caption=caption_for_album
                        )
                    else:
                        logger.warning(
                            f"LISTENER: Album from {raw_source_id} had grouped_id but no media files extracted. Sending original trigger message.")
                        await retry_on_flood(telethon_client_instance.send_message, target_channel_id, message=message)
            else:
                logger.info(f"LISTENER: Sending single message from {raw_source_id} to {target_channel_id}.")
                await retry_on_flood(telethon_client_instance.send_message, target_channel_id, message=message)
            logger.info(f"LISTENER: Message from {raw_source_id} (msg_id: {message.id}) copied to {target_channel_id}.")
        except Exception as e:
            logger.error(f"LISTENER: Error during direct copy from {raw_source_id} to {target_channel_id}: {e}",
                         exc_info=True)
            if moderation_destination_chat_id:
                try:
                    await aiogram_bot_instance.send_message(moderation_destination_chat_id,
                                                            f"⚠️ Ошибка прямого копирования из {raw_source_id} в {target_channel_id}: {e}")
                except Exception:
                    pass


async def start_telethon_listener(client: TelegramClient, aiogram_bot: AiogramBot):
    global listener_task

    async def handle_new_message_wrapper(event):
        await handle_new_message(event, aiogram_bot_instance=aiogram_bot, telethon_client_instance=client)

    source_channel_ids_int = []
    if config.current_settings["source_channels"]:
        try:
            source_channel_ids_int = [int(id_str) for id_str in config.current_settings["source_channels"].keys()]
        except ValueError:
            logger.error("LISTENER: Error converting source_channel_ids to int. Check settings.json.", exc_info=True)
            source_channel_ids_int = []

    if not source_channel_ids_int:
        logger.info("LISTENER: No source channels configured. Telethon listener will not be active or will be stopped.")
        active_handlers = client.list_event_handlers()
        for handler_tuple in active_handlers:
            cb = None
            ev_builder = None
            if len(handler_tuple) == 2:
                cb = handler_tuple[1] if callable(handler_tuple[1]) else handler_tuple[0]
                ev_builder = handler_tuple[0] if isinstance(handler_tuple[0], events.common.EventBuilder) else \
                    handler_tuple[1]

            if cb and cb.__name__ == 'handle_new_message_wrapper' and isinstance(ev_builder, events.NewMessage):
                client.remove_event_handler(cb, ev_builder)
                logger.info("LISTENER: Removed previous NewMessage handler due to no sources.")
        return

    active_handlers = client.list_event_handlers()
    for handler_tuple in active_handlers:
        cb = None
        ev_builder = None
        if len(handler_tuple) == 2:
            cb = handler_tuple[1] if callable(handler_tuple[1]) else handler_tuple[0]
            ev_builder = handler_tuple[0] if isinstance(handler_tuple[0], events.common.EventBuilder) else \
                handler_tuple[1]

        if cb and cb.__name__ == 'handle_new_message_wrapper' and isinstance(ev_builder, events.NewMessage):
            client.remove_event_handler(cb, ev_builder)
            logger.info("LISTENER: Removed old NewMessage handler before adding new one.")

    client.add_event_handler(handle_new_message_wrapper, events.NewMessage(chats=source_channel_ids_int))
    logger.info(f"LISTENER: Telethon client listener started/updated for channels: {source_channel_ids_int}")


async def stop_telethon_listener(client: TelegramClient):
    global listener_task
    if listener_task and not listener_task.done():
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        logger.info("LISTENER: Telethon listener task (run_until_disconnected) stopped.")
    listener_task = None

    active_handlers = client.list_event_handlers()
    for handler_tuple in active_handlers:
        cb = None
        ev_builder = None
        if len(handler_tuple) == 2:
            cb = handler_tuple[1] if callable(handler_tuple[1]) else handler_tuple[0]
            ev_builder = handler_tuple[0] if isinstance(handler_tuple[0], events.common.EventBuilder) else \
                handler_tuple[1]

        if cb and cb.__name__ == 'handle_new_message_wrapper' and isinstance(ev_builder, events.NewMessage):
            client.remove_event_handler(cb, ev_builder)
            logger.info("LISTENER: NewMessage handler removed upon stopping listener.")
