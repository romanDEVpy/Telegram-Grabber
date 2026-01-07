from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any


def main_admin_keyboard(premoderation_enabled: bool, target_channel_id: int | None,
                        target_channel_title: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить источник", callback_data="add_source_channel")
    builder.button(text="➖ Удалить источник",
                   callback_data="remove_source_channel_select")  # Changed target for clarity

    target_status = f"✅ {target_channel_title} ({target_channel_id})" if target_channel_id and target_channel_title else "❌ Не задан"
    builder.button(text=f"🎯 Целевой канал: {target_status}", callback_data="set_target_channel")

    mod_status = "Включена ✅" if premoderation_enabled else "Выключена ❌"
    builder.button(text=f"📝 Предмодерация: {mod_status}", callback_data="toggle_premoderation")

    builder.button(text="📋 Список источников", callback_data="list_source_channels_page_0")  # Start with page 0
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


def confirm_remove_keyboard(channel_id_to_remove: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_remove_{channel_id_to_remove}")
    builder.button(text="❌ Отмена", callback_data="admin_panel")  # Back to main menu on cancel
    return builder.as_markup()


def moderation_keyboard(original_message_id: int, original_chat_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Одобрить", callback_data=f"mod_approve:{original_chat_id}:{original_message_id}")
    builder.button(text="❌ Отклонить", callback_data=f"mod_reject:{original_chat_id}:{original_message_id}")
    return builder.as_markup()


def back_to_admin_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в админ-меню", callback_data="admin_panel")
    return builder.as_markup()


def list_sources_keyboard(source_channels_data: Dict[str, Dict[str, str]], page: int = 0,
                          page_size: int = 5) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    channel_items = list(source_channels_data.items())  # List of (resolved_id, {"input_value": "...", "title": "..."})
    start_index = page * page_size
    end_index = start_index + page_size

    for channel_id_str, data in channel_items[start_index:end_index]:
        channel_id = int(channel_id_str)  # Keys in JSON are strings
        display_name = data.get("title", data.get("input_value", f"ID: {channel_id}"))
        input_val = data.get("input_value", f"ID: {channel_id}")

        text = f"🗑️ {display_name}"
        if display_name != input_val and input_val != f"ID: {channel_id}":  # Show input_value if different and not just ID
            text += f" ({input_val})"

        builder.button(text=text, callback_data=f"request_remove_{channel_id}")

    total_pages = (len(channel_items) + page_size - 1) // page_size

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"list_source_channels_page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️ След.", callback_data=f"list_source_channels_page_{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(text="⬅️ Назад в админ-меню", callback_data="admin_panel"))
    builder.adjust(1)  # Each source button on a new line
    return builder.as_markup()
