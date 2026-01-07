from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient
from telethon.tl.types import Channel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import ChannelPrivateError, UserAlreadyParticipantError, InviteHashExpiredError

import config
from app.states.admin_states import AdminStates
from app.keyboards.inline import main_admin_keyboard, confirm_remove_keyboard, back_to_admin_menu_keyboard, \
    list_sources_keyboard
from app.utils.tools import resolve_entity_details, is_admin
from app.handlers.common import get_target_channel_title  # Re-use common function

router = Router()


async def get_admin_panel_markup(bot_instance: Bot):
    target_title = await get_target_channel_title(bot_instance)
    return main_admin_keyboard(
        config.current_settings["premoderation_enabled"],
        config.current_settings["target_channel_id"],
        target_title
    )


@router.callback_query(F.data == "add_source_channel")
async def cq_add_source_channel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    await callback.message.edit_text(
        "Введите ссылку, @username или ID канала-источника:",
        reply_markup=back_to_admin_menu_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_source_channel)
    await callback.answer()


@router.message(AdminStates.waiting_for_source_channel)
async def process_source_channel_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id, config.ADMIN_IDS):
        await message.answer("Доступ запрещен.")
        await state.clear()
        return

    channel_input = message.text.strip()
    telethon_client: TelegramClient = bot.telethon_client
    admin_panel_markup = await get_admin_panel_markup(bot)

    if not telethon_client or not telethon_client.is_connected():
        await message.answer("Клиент Telethon не активен. Попробуйте позже или перезапустите бота.",
                             reply_markup=admin_panel_markup)
        await state.clear()
        return

    await message.answer("⏳ Проверяю канал...")

    entity_details = await resolve_entity_details(telethon_client, channel_input)

    if entity_details:
        resolved_id, title, entity_type = entity_details
        if entity_type not in ["channel", "chat"]:  # Allow chats as well
            await message.answer(f"❌ Сущность '{title}' не является каналом или чатом.",
                                 reply_markup=admin_panel_markup)
            await state.clear()
            return

        # Нормализуем ID для консистентного хранения
        resolved_id_str = config.normalize_channel_id(resolved_id)

        if resolved_id_str in config.current_settings["source_channels"]:
            await message.answer(f"Канал/чат '{title}' ({resolved_id}) уже есть в списке источников.",
                                 reply_markup=admin_panel_markup)
        else:
            # Автоматическая подписка на канал
            subscription_status = ""
            try:
                # Проверяем, подписаны ли уже
                try:
                    participant = await telethon_client.get_permissions(resolved_id, 'me')
                    is_subscribed = participant is not None
                except:
                    is_subscribed = False

                if not is_subscribed and entity_type == "channel":
                    # Пытаемся подписаться
                    try:
                        entity = await telethon_client.get_entity(resolved_id)
                        await telethon_client(JoinChannelRequest(entity))
                        subscription_status = "\n📥 Автоматически подписались на канал."
                    except UserAlreadyParticipantError:
                        subscription_status = "\n✅ Уже подписаны на канал."
                    except ChannelPrivateError:
                        subscription_status = "\n⚠️ Приватный канал - подпишитесь вручную через invite link."
                    except InviteHashExpiredError:
                        subscription_status = "\n⚠️ Ссылка-приглашение устарела - получите новую."
                    except Exception as sub_error:
                        subscription_status = f"\n⚠️ Не удалось подписаться автоматически: {sub_error}\nПодпишитесь вручную."
                elif is_subscribed:
                    subscription_status = "\n✅ Уже подписаны на канал."
                elif entity_type == "chat":
                    subscription_status = "\n💬 Это чат (группа) - убедитесь, что вы участник."

                # Финальная проверка доступа
                await telethon_client.get_entity(resolved_id)

                # Добавляем в настройки
                config.current_settings["source_channels"][resolved_id_str] = {"input_value": channel_input,
                                                                               "title": title}
                config.save_settings()
                await message.answer(
                    f"✅ Канал/чат '{title}' (ID: {resolved_id}) успешно добавлен в источники.{subscription_status}",
                    reply_markup=admin_panel_markup
                )

                if hasattr(bot, 'restart_telethon_listener'):
                    await bot.restart_telethon_listener()
            except Exception as e:
                await message.answer(
                    f"⚠️ Не удалось получить доступ к каналу/чату '{title}'. Убедитесь, что аккаунт Telethon имеет доступ. Ошибка: {e}",
                    reply_markup=admin_panel_markup)
    else:
        await message.answer(f"❌ Не удалось распознать канал/чат '{channel_input}'. Проверьте правильность ввода.",
                             reply_markup=admin_panel_markup)

    await state.clear()


@router.callback_query(F.data == "remove_source_channel_select")
async def cq_remove_source_channel_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    if not config.current_settings["source_channels"]:
        await callback.answer("Список источников пуст.", show_alert=True)
        return

    await callback.message.edit_text(
        "Выберите канал/чат для удаления:",
        reply_markup=list_sources_keyboard(config.current_settings["source_channels"], page=0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("list_source_channels_page_"))
async def cq_list_source_page(callback: CallbackQuery, bot: Bot):  # Added bot for admin panel markup
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    page = int(callback.data.split("_")[-1])

    sources = config.current_settings.get("source_channels", {})
    if not sources and page == 0:  # No sources at all
        admin_panel_markup = await get_admin_panel_markup(bot)
        await callback.message.edit_text("Список источников пуст.", reply_markup=admin_panel_markup)
        await callback.answer()
        return

    # Dynamic update of titles for listing (optional, can be heavy)
    # For now, uses stored titles.

    await callback.message.edit_text(
        "Текущие источники (нажмите для удаления):" if sources else "Список источников пуст.",
        reply_markup=list_sources_keyboard(sources, page=page) if sources else await get_admin_panel_markup(bot)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("request_remove_"))
async def cq_request_remove_source(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    channel_id_to_remove = int(callback.data.split("_")[-1])
    channel_id_str = str(channel_id_to_remove)

    channel_data = config.current_settings["source_channels"].get(channel_id_str)
    if not channel_data:
        await callback.answer("Источник не найден, возможно уже удален.", show_alert=True)
        return

    channel_display_name = channel_data.get("title", channel_data.get("input_value", f"ID: {channel_id_to_remove}"))

    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить источник: {channel_display_name}?",
        reply_markup=confirm_remove_keyboard(channel_id_to_remove)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_remove_"))
async def cq_confirm_remove_source(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    channel_id_to_remove = int(callback.data.split("_")[-1])
    channel_id_str = str(channel_id_to_remove)
    admin_panel_markup = await get_admin_panel_markup(bot)

    if channel_id_str in config.current_settings["source_channels"]:
        removed_channel_data = config.current_settings["source_channels"].pop(channel_id_str)
        removed_display_name = removed_channel_data.get("title", removed_channel_data.get("input_value",
                                                                                          f"ID: {channel_id_to_remove}"))
        config.save_settings()
        await callback.message.edit_text(
            f"✅ Источник '{removed_display_name}' удален.",
            reply_markup=admin_panel_markup
        )
        if hasattr(bot, 'restart_telethon_listener'):
            await bot.restart_telethon_listener()
    else:
        await callback.message.edit_text(
            "❌ Источник не найден. Возможно, он уже был удален.",
            reply_markup=admin_panel_markup
        )
    await callback.answer()


@router.callback_query(F.data == "set_target_channel")
async def cq_set_target_channel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    await callback.message.edit_text(
        "Введите ссылку, @username или ID целевого канала/чата (куда будут копироваться посты):",
        reply_markup=back_to_admin_menu_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_target_channel)
    await callback.answer()


@router.message(AdminStates.waiting_for_target_channel)
async def process_target_channel_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id, config.ADMIN_IDS):
        await message.answer("Доступ запрещен.")
        await state.clear()
        return

    channel_input = message.text.strip()
    telethon_client: TelegramClient = bot.telethon_client
    admin_panel_markup = await get_admin_panel_markup(bot)

    if not telethon_client or not telethon_client.is_connected():
        await message.answer("Клиент Telethon не активен.", reply_markup=admin_panel_markup)
        await state.clear()
        return

    await message.answer("⏳ Проверяю канал/чат...")
    entity_details = await resolve_entity_details(telethon_client, channel_input)

    if entity_details:
        resolved_id, title, entity_type = entity_details
        if entity_type not in ["channel", "chat"]:
            await message.answer(f"❌ Сущность '{title}' не является каналом или чатом.",
                                 reply_markup=admin_panel_markup)
            await state.clear()
            return

        try:
            entity = await telethon_client.get_entity(resolved_id)
            # Basic check if it's a channel/megagroup. Further permission check is harder.
            if not (isinstance(entity, Channel) or (hasattr(entity, 'megagroup') and entity.megagroup)):
                if not (hasattr(entity, 'broadcast') and entity.broadcast):  # Check if it's a channel
                    await message.answer(
                        f"❌ Сущность '{title}' (ID: {resolved_id}) не является каналом или супергруппой, куда можно слать посты.",
                        reply_markup=admin_panel_markup)
                    await state.clear()
                    return

            config.current_settings["target_channel_id"] = resolved_id
            # Store title for display purposes, though it's fetched dynamically in keyboard now
            # config.current_settings["target_channel_title"] = title # Example if needed
            config.save_settings()

            # Re-fetch admin panel markup to reflect new target title
            admin_panel_markup_updated = await get_admin_panel_markup(bot)
            await message.answer(f"✅ Целевой канал/чат '{title}' (ID: {resolved_id}) установлен.",
                                 reply_markup=admin_panel_markup_updated)
        except Exception as e:
            await message.answer(
                f"⚠️ Не удалось получить доступ или проверить целевой канал/чат '{title}'. Ошибка: {e}",
                reply_markup=admin_panel_markup)
    else:
        await message.answer(f"❌ Не удалось распознать целевой канал/чат '{channel_input}'.",
                             reply_markup=admin_panel_markup)

    await state.clear()


@router.callback_query(F.data == "toggle_premoderation")
async def cq_toggle_premoderation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(callback.from_user.id, config.ADMIN_IDS):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    config.current_settings["premoderation_enabled"] = not config.current_settings["premoderation_enabled"]
    config.save_settings()

    admin_panel_markup = await get_admin_panel_markup(bot)
    status_text = "Включена ✅" if config.current_settings["premoderation_enabled"] else "Выключена ❌"

    await callback.message.edit_text(
        f"Предмодерация теперь {status_text.lower()}",
        reply_markup=admin_panel_markup
    )

    alert_message = None
    if config.current_settings["premoderation_enabled"]:
        if not config.ADMIN_IDS:
            alert_message = "Внимание: Предмодерация включена, но ADMIN_IDS не заданы!"
        elif not config.current_settings.get("moderation_chat_id"):
            first_admin_id = config.ADMIN_IDS[0]
            config.current_settings["moderation_chat_id"] = first_admin_id
            config.save_settings()
            alert_message = f"Посты на модерацию будут отправляться админу {first_admin_id}."

    if alert_message:
        await callback.answer(alert_message, show_alert=True)
    else:
        await callback.answer(f"Предмодерация {status_text.lower()}")
