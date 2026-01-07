from telethon import TelegramClient
from telethon.tl.types import PeerChannel, PeerChat, PeerUser, Channel, Chat, User
from telethon.errors import (
    UserNotParticipantError, ChannelPrivateError, ChatAdminRequiredError,
    UsernameNotOccupiedError, UsernameInvalidError,
    FloodWaitError
)

from aiogram.types import Message
from typing import Optional, Tuple


async def resolve_entity_details(client: TelegramClient, entity_input: str) -> Optional[Tuple[int, str, str]]:
    resolved_id: Optional[int] = None
    title: str = entity_input
    entity_type_str: str = "unknown"

    try:
        if entity_input.isdigit() or (entity_input.startswith('-') and entity_input[1:].isdigit()):
            try:
                entity_id_int = int(entity_input)
                entity = await client.get_entity(entity_id_int)
                resolved_id = entity.id
                title = getattr(entity, 'title', getattr(entity, 'username', str(resolved_id)))
            except (ValueError, TypeError, AttributeError):
                pass
            except FloodWaitError as e:
                print(f"Flood wait error when resolving entity by ID '{entity_input}': {e}")
                return None
            except Exception as e:
                print(f"Error resolving entity by ID '{entity_input}': {e}")
                pass

        if resolved_id is None:
            entity = await client.get_entity(entity_input)
            resolved_id = entity.id
            if hasattr(entity, 'title'):
                title = entity.title
            elif hasattr(entity, 'username') and entity.username:
                title = f"@{entity.username}"
            elif hasattr(entity, 'first_name'):
                title = entity.first_name
                if hasattr(entity, 'last_name') and entity.last_name:
                    title += f" {entity.last_name}"
            else:
                title = str(resolved_id)

        if isinstance(entity, Channel):
            entity_type_str = "channel"
        elif isinstance(entity, Chat):
            entity_type_str = "chat"
        elif isinstance(entity, User):
            entity_type_str = "user"

        return resolved_id, title, entity_type_str


    except (ValueError, UsernameNotOccupiedError, UsernameInvalidError) as e:
        print(f"Could not resolve entity '{entity_input}': {e}")
        return None
    except FloodWaitError as e:
        print(f"Flood wait error when resolving entity '{entity_input}': {e}")
        return None
    except Exception as e:
        print(f"Unexpected error resolving entity '{entity_input}': {e}")
        return None


def is_admin(message_or_user_id, admin_ids: list[int]) -> bool:
    user_id = message_or_user_id.from_user.id if isinstance(message_or_user_id, Message) else message_or_user_id
    return user_id in admin_ids
