import asyncio
import os
import sys
from typing import Iterable

import requests
from telebot import TeleBot

from pymax import SocketMaxClient
from pymax.crud import Database
from pymax.payloads import UserAgentPayload
from pymax.types import PhotoAttach, VideoAttach
from dotenv import load_dotenv


def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        print(f"Missing required env var: {name}")
        sys.exit(2)
    return value


def summarize_attaches(attaches: Iterable[object] | None) -> str:
    if not attaches:
        return ""
    type_names = [type(a).__name__ for a in attaches]
    counts: dict[str, int] = {}
    for name in type_names:
        counts[name] = counts.get(name, 0) + 1
    items = ", ".join(f"{k} x{v}" for k, v in counts.items())
    return f"\n\nAttachments: {items}"


def format_message_details(message: object, sender_name: str | None = None) -> str:
    def safe_get(name: str) -> str:
        value = getattr(message, name, None)
        return "" if value is None else str(value)

    fields = {
        "Sender Name": sender_name or "",
        "Reaction": safe_get("reactionInfo"),
    }

    lines = ["MAX message"]
    for label, value in fields.items():
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def build_client() -> SocketMaxClient:
    phone = get_env("MAX_PHONE")
    session_name = os.getenv("MAX_SESSION", "session.db")
    token = os.getenv("MAX_TOKEN")
    work_dir = os.getenv("MAX_WORK_DIR", ".")
    device_type = os.getenv("MAX_DEVICE_TYPE", "DESKTOP")
    app_version = os.getenv("MAX_APP_VERSION", "25.12.13")
    force_code = os.getenv("MAX_FORCE_CODE", "false").lower() in {"1", "true", "yes"}

    ua = UserAgentPayload(device_type=device_type, app_version=app_version)

    client = SocketMaxClient(
        phone=phone,
        session_name=session_name,
        token=token,
        work_dir=work_dir,
        headers=ua,
    )

    return client


def get_session_token(work_dir: str) -> str | None:
    try:
        return Database(work_dir).get_auth_token()
    except Exception:
        return None


def get_user_display_name(user: object | None) -> str | None:
    if not user:
        return None
    names = getattr(user, "names", None)
    if not names:
        return None
    name = names[0]
    first_name = getattr(name, "first_name", None)
    last_name = getattr(name, "last_name", None)
    full = " ".join(part for part in [first_name, last_name] if part)
    return full or getattr(name, "name", None)


def download_file(url: str, destination: str) -> None:
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                file.write(chunk)


async def save_and_send_media(
    client: SocketMaxClient,
    message: object,
    bot: TeleBot,
    chat_id: str,
    media_dir: str,
) -> None:
    attaches = getattr(message, "attaches", None) or []
    if not attaches:
        return

    os.makedirs(media_dir, exist_ok=True)

    for attach in attaches:
        if isinstance(attach, PhotoAttach):
            url = attach.base_url
            if not url:
                continue
            filename = f"photo_{getattr(message, 'id', 'unknown')}_{attach.photo_id}.jpg"
            path = os.path.join(media_dir, filename)
            await asyncio.to_thread(download_file, url, path)
            await asyncio.to_thread(lambda: bot.send_photo(chat_id, open(path, "rb")))
            os.remove(path)
        elif isinstance(attach, VideoAttach):
            video = await client.get_video_by_id(
                chat_id=getattr(message, "chat_id", 0),
                message_id=getattr(message, "id", 0),
                video_id=attach.video_id,
            )
            if not video or not video.url:
                continue
            filename = f"video_{getattr(message, 'id', 'unknown')}_{attach.video_id}.mp4"
            path = os.path.join(media_dir, filename)
            await asyncio.to_thread(download_file, video.url, path)
            await asyncio.to_thread(lambda: bot.send_video(chat_id, open(path, "rb")))
            os.remove(path)


async def main() -> None:
    load_dotenv()
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    bot = TeleBot(bot_token)
    source_chat_title = os.getenv("MAX_SOURCE_CHAT_TITLE", "").strip()
    source_chat_id_env = os.getenv("MAX_SOURCE_CHAT_ID", "").strip()
    source_chat_id: int | None = None

    client = build_client()

    work_dir = os.getenv("MAX_WORK_DIR", ".")
    session_path = os.path.join(work_dir, os.getenv("MAX_SESSION", "session.db"))
    has_session = os.path.exists(session_path)
    session_token = get_session_token(work_dir) if has_session else None
    has_session_token = bool(session_token)
    force_code = os.getenv("MAX_FORCE_CODE", "false").lower() in {"1", "true", "yes"}

    if force_code or (not os.getenv("MAX_TOKEN") and not has_session_token):
        language = os.getenv("MAX_LANGUAGE", "ru")
        if not getattr(client, "is_connected", False):
            await client.connect()
        temp_token = await client.request_code(phone=client.phone, language=language)
        code = input("Enter MAX verification code: ").strip()
        await client.login_with_code(temp_token=temp_token, code=code, start=False)

    @client.on_start
    async def on_start() -> None:
        nonlocal source_chat_id
        if source_chat_title:
            for chat in client.chats:
                if chat.title and chat.title.strip().lower() == source_chat_title.lower():
                    source_chat_id = chat.id
                    break
            if source_chat_id is None:
                print(f"MAX_SOURCE_CHAT_TITLE not found: {source_chat_title}")

        if source_chat_id is None and source_chat_id_env:
            try:
                source_chat_id = int(source_chat_id_env)
            except ValueError:
                print("MAX_SOURCE_CHAT_ID must be a number")

    @client.on_message()
    async def handle_message(message):
        if source_chat_id is not None and message.chat_id != source_chat_id:
            return
        sender_name = None
        if message.sender:
            user = await client.get_user(message.sender)
            sender_name = get_user_display_name(user)
        text = message.text or ""
        summary = f"{format_message_details(message, sender_name)}\nText: {text}"
        summary += summarize_attaches(message.attaches)
        await asyncio.to_thread(bot.send_message, chat_id, summary)
        await save_and_send_media(client, message, bot, chat_id, os.getenv("MAX_MEDIA_DIR", "media"))

    await client.start()
    await client.idle()


if __name__ == "__main__":
    asyncio.run(main())
