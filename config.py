import os
import json
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

load_dotenv()

BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
API_ID: Optional[str] = os.getenv("API_ID")
API_HASH: Optional[str] = os.getenv("API_HASH")
PHONE_NUMBER: Optional[str] = os.getenv("PHONE_NUMBER")

raw_admin_ids: str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = []
if raw_admin_ids:
    try:
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in raw_admin_ids.split(',')]
    except ValueError:
        print("ERROR: ADMIN_IDS in .env contains non-numeric values.")

if not BOT_TOKEN or not API_ID or not API_HASH:
    raise ValueError(
        "One or more mandatory environment variables are not set: "
        "BOT_TOKEN, API_ID, API_HASH"
    )

SETTINGS_FILE: str = "data/settings.json"
MODERATION_QUEUE_FILE: str = "data/moderation_queue.json"
DATA_DIR: str = "data"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "target_channel_id": None,
    "source_channels": {},  # Stores {resolved_id: {"input_value": "...", "title": "..."}}
    "premoderation_enabled": True,
    "moderation_chat_id": None
}

current_settings: Dict[str, Any] = {}


def load_settings() -> Dict[str, Any]:
    global current_settings
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings_from_file = json.load(f)
            # Ensure all default keys exist
            for key, value in DEFAULT_SETTINGS.items():
                settings_from_file.setdefault(key, value)
            current_settings = settings_from_file
    except (FileNotFoundError, json.JSONDecodeError):
        current_settings = DEFAULT_SETTINGS.copy()
        save_settings()  # Save default settings if file not found or corrupted
    return current_settings


def save_settings() -> None:
    """Атомарно сохраняет настройки через временный файл для предотвращения коррупции данных"""
    global current_settings
    os.makedirs(DATA_DIR, exist_ok=True)

    # Записываем во временный файл
    temp_file = SETTINGS_FILE + '.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, indent=4, ensure_ascii=False)

        # Атомарно заменяем основной файл
        if os.path.exists(SETTINGS_FILE):
            os.replace(temp_file, SETTINGS_FILE)
        else:
            os.rename(temp_file, SETTINGS_FILE)
    except Exception as e:
        # Если что-то пошло не так, удаляем временный файл
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise e


# Load settings on module import
load_settings()


# Очередь модерации
moderation_queue: Dict[str, Dict[str, Any]] = {}


def load_moderation_queue() -> Dict[str, Dict[str, Any]]:
    """Загружает очередь модерации из файла"""
    global moderation_queue
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(MODERATION_QUEUE_FILE, 'r', encoding='utf-8') as f:
            moderation_queue = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        moderation_queue = {}
    return moderation_queue


def save_moderation_queue() -> None:
    """Атомарно сохраняет очередь модерации"""
    global moderation_queue
    os.makedirs(DATA_DIR, exist_ok=True)

    temp_file = MODERATION_QUEUE_FILE + '.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(moderation_queue, f, indent=4, ensure_ascii=False)

        if os.path.exists(MODERATION_QUEUE_FILE):
            os.replace(temp_file, MODERATION_QUEUE_FILE)
        else:
            os.rename(temp_file, MODERATION_QUEUE_FILE)
    except Exception as e:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise e


def add_to_moderation_queue(message_key: str, original_chat_id: int, original_message_id: int) -> None:
    """Добавляет сообщение в очередь модерации"""
    global moderation_queue
    moderation_queue[message_key] = {
        "original_chat_id": original_chat_id,
        "original_message_id": original_message_id
    }
    save_moderation_queue()


def remove_from_moderation_queue(message_key: str) -> None:
    """Удаляет сообщение из очереди модерации"""
    global moderation_queue
    if message_key in moderation_queue:
        del moderation_queue[message_key]
        save_moderation_queue()


# Загрузить очередь модерации при импорте модуля
load_moderation_queue()


def normalize_channel_id(channel_id: int) -> str:
    """
    Нормализует ID канала/чата к единому формату строки для хранения и сравнения.
    Telegram использует разные форматы ID:
    - Каналы/супергруппы: -100xxxxxxxxxx
    - Обычные группы: -xxxxxxxxx
    - Пользователи: положительные числа

    Для хранения в settings используем ID без префикса -100
    """
    if channel_id < -100000000000:
        # Убираем префикс -100 для супергрупп/каналов
        return str(channel_id)[4:]
    else:
        # Для обычных групп и пользователей оставляем как есть
        return str(channel_id)
