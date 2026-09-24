from pathlib import Path
from pymax import Client, Photo, Video, File, Voice

from debug import debug_log

def _get_name(user) -> list[str]:
    names = []
    if user is None:
        return names
    for name in user.names:
        if name.name:
            names.append(name.name)
        parts = [p for p in (name.first_name, name.last_name) if p]
        if parts:
            names.append(" ".join(parts))
    return names

async def send_message_from_tg(chat_recipient: str, media: dict | None, text: str, client: Client) -> None:
    my_id = client.me.contact.id if client.me else None
    
    chats = await client.fetch_chats()

    for chat in chats:
        chat_title = chat.title
        
        chat_type = str(getattr(chat, "type", ""))
        is_dialog = chat_type in ("DIALOG", "ChatType.DIALOG")

        if is_dialog:
            user_id = [uid for uid in chat.participants.keys() if uid != my_id]
            if user_id:
                user = await client.get_user(user_id[0]) if user_id else None
                debug_log(f"User ID: {user_id}, User: {user}")
                try:
                    full_names = _get_name(user)
                    for full_name in full_names:
                        if full_name == chat_recipient:
                            debug_log (f"{full_name} \n")
                            chat_title = full_name
                            break
                        else:
                            continue
                except Exception as e:
                    debug_log(f"Error {e}")
        debug_log(f"Checking chat.id: {chat.id}, chat.title: {chat_title} \n")
        if chat_title == chat_recipient and (media or len(text) > 0):
            for key, value in (media or {}).items():
                if key == "photo":
                    media_file = Photo(path=Path(value))
                    await client.send_message(chat_id=chat.id, attachments=[media_file])
                    Path(value).unlink(missing_ok=True)
                elif key == "video":
                    media_file = Video(path=Path(value))
                    await client.send_message(chat_id=chat.id, attachments=[media_file])
                    Path(value).unlink(missing_ok=True)
                elif key == "document":
                    media_file = File(path=Path(value))
                    await client.send_message(chat_id=chat.id, attachments=[media_file])
                    Path(value).unlink(missing_ok=True)
                elif key == "voice":
                    media_file = Voice(path=Path(value))
                    await client.send_message(chat_id=chat.id, attachments=[media_file])
                    Path(value).unlink(missing_ok=True)
            if len(text) > 0:
                await client.send_message(chat_id=chat.id, text=text)
            debug_log(f"Sent message to chat {chat_recipient}")
            return

    debug_log(f"Chat with title {chat_recipient} was not found")
