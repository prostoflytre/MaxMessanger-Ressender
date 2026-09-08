import asyncio
import os
import sys
from typing import Iterable
from pymax import Client

import requests
from telebot import TeleBot
from imagekitio import ImageKit

from pymax import ExtraConfig
from pymax.types import PhotoAttachment, VideoAttachment
from dotenv import load_dotenv

# Create Client and start it
def build_client() -> Client:
    phone = get_env("MAX_PHONE")
    session_name = os.getenv("MAX_SESSION", "session.db")
    token = os.getenv("MAX_TOKEN")
    work_dir = os.getenv("MAX_WORK_DIR", ".")
    device_type = os.getenv("MAX_DEVICE_TYPE", "DESKTOP")

    client = Client(
        phone=phone,
        session_name=session_name,
        work_dir=work_dir,
        extra_config=ExtraConfig(token=token, device_type=device_type),
    )

    return client

# Output in console
def debug_log(message: str) -> None:
    enabled = os.getenv("MAX_DEBUG", "true").lower() in {"1", "true", "yes"}
    if enabled:
        print(f"[MaxRessend] {message}")

# get env data, with output in console if missing
def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        print(f"Missing required env var: {name}")
        sys.exit(2)
    return value

# func of getting attaches in a dict of their counts
def summarize_attaches(attaches: Iterable[object] | None) -> str:
    if not attaches:
        return ""
    type_names = [type(a).__name__ for a in attaches]
    counts: dict[str, int] = {}
    for name in type_names:
        counts[name] = counts.get(name, 0) + 1
    items = ", ".join(f"{k} x{v}" for k, v in counts.items())
    return f"\n\nAttachments: {items}"

# get message info as a formatted string with reaction info
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




# get user display name from message
def get_user_display_name(user: object | None) -> str | None:
    if not user:
        return None
    names = getattr(user, "names", None)
    if not names:
        return None
    name = names[0]
    first_name = getattr(name, "first_name", None)
    last_name = getattr(name, "last_name", None)
    # Combine first and last name if not None, false or empty
    full = " ".join(part for part in [first_name, last_name] if part) 
    return full or getattr(name, "name", None)

# download file from url to destination
def download_file(url: str, destination: str) -> None:
    debug_log(f"download_file start url={url} destination={destination}")
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status() # get a exception if the request failed
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024 * 256): # read in 256 KB chunks
            if chunk:
                file.write(chunk)
    debug_log(f"download_file done destination={destination}")

# upload file to ImageKit and return the uploaded URL
def upload_file_to_imagekit(file_path: str, file_name: str) -> str | None:
    private_key = os.getenv("IMAGEKIT_PRIVATE_KEY", "").strip()
    imagekit_folder = os.getenv("IMAGEKIT_FOLDER", "/max-messenger")

    if not private_key:
        debug_log("upload_file_to_imagekit skipped: IMAGEKIT_PRIVATE_KEY is empty")
        return None

    imagekit = ImageKit(
        private_key=private_key,
    )

    with open(file_path, "rb") as file:
        debug_log(f"upload_file_to_imagekit start file_name={file_name}")
        response = imagekit.files.upload(
            file=file,
            file_name=file_name,
            folder=imagekit_folder,
            use_unique_file_name=True,
        )

    if isinstance(response, dict):
        uploaded_url = response.get("url")
        debug_log(f"upload_file_to_imagekit done url={uploaded_url}")
        return uploaded_url
    uploaded_url = getattr(response, "url", None)
    debug_log(f"upload_file_to_imagekit done url={uploaded_url}")
    return uploaded_url

# get link to media sources from a Max message, including forwarded messages 
def get_media_sources(message: object) -> list[tuple[str, object]]:
    sources: list[tuple[str, object]] = [("", message)]
    link = getattr(message, "link", None)
    forwarded_message = getattr(link, "message", None) if link else None
    if forwarded_message is not None:
        sources.append(("forwarded", forwarded_message))
    return sources

# get list of id values that are positive integers and unique
def _unique_positive_ints(values: Iterable[object]) -> list[int]:
    result: list[int] = []
    for value in values:
        if isinstance(value, int) and value > 0 and value not in result:
            result.append(value)
    return result

# Get video URL from a Max message by resolving video ID
async def resolve_video_url(
    client: Client,
    parent_message: object,
    source_message: object,
    video_id: int,
) -> str | None:

    # Extract link and linked message from the parent message
    link = getattr(parent_message, "link", None)
    linked_message = getattr(link, "message", None) if link else None

    chat_ids = _unique_positive_ints(
        [
            getattr(source_message, "chat_id", None),
            getattr(source_message, "cid", None),
            getattr(link, "chat_id", None),
            getattr(parent_message, "chat_id", None),
        ]
    )
    message_ids = _unique_positive_ints(
        [
            getattr(source_message, "id", None),
            getattr(linked_message, "id", None),
            getattr(parent_message, "id", None),
        ]
    )

    for chat_id_candidate in chat_ids:
        for message_id_candidate in message_ids:
            try:
                video = await client.get_video_by_id(
                    chat_id=chat_id_candidate,
                    message_id=message_id_candidate,
                    video_id=video_id,
                )
                if video and video.url:
                    return video.url
            except Exception:
                continue

    return None

# Process media from Max and create ImageKit uploads
async def process_media_source(
    client: Client,
    parent_message: object,
    source_message: object,
    source_label: str,
    bot: TeleBot,
    chat_id: str,
    media_dir: str,
) -> None:
    attaches = getattr(source_message, "attaches", None) or []
    if not attaches:
        debug_log(f"process_media_source no attaches source={source_label or 'main'}")
        return

    debug_log(
        f"process_media_source start source={source_label or 'main'} attaches={len(attaches)} message_id={getattr(source_message, 'id', None)}"
    )

    for attach in attaches:
        media_kind = ""
        source_url: str | None = None
        filename = ""
        if isinstance(attach, PhotoAttachment):
            source_url = attach.base_url
            if not source_url:
                continue
            media_kind = "photo"
            filename = f"photo_{getattr(source_message, 'id', 'unknown')}_{attach.photo_id}.jpg" # save photo with message ID and photo ID
        elif isinstance(attach, VideoAttachment):
            source_url = await resolve_video_url(
                client=client,
                parent_message=parent_message,
                source_message=source_message,
                video_id=attach.video_id,
            )
            # If video URL could not be resolved, try using the thumbnail as a preview
            if not source_url and getattr(attach, "thumbnail", None):
                source_url = attach.thumbnail
                media_kind = "video-preview"
                filename = (
                    f"video_preview_{getattr(source_message, 'id', 'unknown')}_{attach.video_id}.jpg"
                )
            if not source_url:
                await asyncio.to_thread(
                    bot.send_message,
                    chat_id,
                    f"MAX video не удалось получить (id={attach.video_id}) в этом контексте сообщения.",
                )
                continue
            if media_kind != "video-preview": # Only set as video if it's not a preview
                media_kind = "video"
                filename = f"video_{getattr(source_message, 'id', 'unknown')}_{attach.video_id}.mp4"

        if not filename:
            debug_log("process_media_source skip: empty filename")
            continue

        if not source_url:
            debug_log(f"process_media_source skip: no source_url kind={media_kind}")
            continue

        # start of download media and upload to ImageKit process
        path = os.path.join(media_dir, filename)
        try:
            debug_log(f"process_media_source download by url kind={media_kind} path={path}")
            await asyncio.to_thread(download_file, source_url, path)

            try:
                debug_log(f"process_media_source upload to imagekit path={path}")
                hosted_url = await asyncio.to_thread(upload_file_to_imagekit, path, filename)
            except Exception as upload_error:
                debug_log(f"process_media_source imagekit error: {upload_error}")
                await asyncio.to_thread(
                    bot.send_message,
                    chat_id,
                    f"Ошибка загрузки MAX {media_kind} в ImageKit: {upload_error}",
                )
                hosted_url = None

            source_prefix = "forwarded " if source_label == "forwarded" else ""
            if hosted_url:
                debug_log(f"process_media_source send telegram link url={hosted_url}")
                await asyncio.to_thread(
                    bot.send_message,
                    chat_id,
                    f"MAX {source_prefix}{media_kind} link: {hosted_url}",
                )
            else:
                debug_log(f"process_media_source no hosted url, local path={path}")
                await asyncio.to_thread(
                    bot.send_message,
                    chat_id,
                    (
                        f"MAX {source_prefix}{media_kind} получен, но не задан IMAGEKIT_PRIVATE_KEY. "
                        f"Файл сохранён локально: {path}"
                    ),
                )
        finally:
            if os.path.exists(path):
                os.remove(path)
                debug_log(f"process_media_source local file removed path={path}") # delete local file after processing

# Save media locally and send it via Telegram, optionally uploading to ImageKit
async def save_and_send_media(
    client: Client,
    message: object,
    bot: TeleBot,
    chat_id: str,
    media_dir: str,
) -> None:
    os.makedirs(media_dir, exist_ok=True)
    for source_label, source_message in get_media_sources(message):
        try:
            await process_media_source(
                client=client,
                parent_message=message,
                source_message=source_message,
                source_label=source_label,
                bot=bot,
                chat_id=chat_id,
                media_dir=media_dir,
            )
        except Exception as media_error:
            await asyncio.to_thread(
                bot.send_message,
                chat_id,
                f"Ошибка обработки MAX media: {media_error}",
            )

# Entry point for the application
async def main() -> None:
    load_dotenv()
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    bot = TeleBot(bot_token)
    source_chat_title = os.getenv("MAX_SOURCE_CHAT_TITLE", "").strip()
    source_chat_id: int | None = os.getenv("MAX_SOURCE_CHAT_ID")

    client = build_client()

    # Event handler for when the client starts
    @client.on_start()
    async def on_start(client: Client) -> None:
        nonlocal source_chat_id
        if source_chat_title:
            for chat in client.chats:
                if chat.title and chat.title.strip().lower() == source_chat_title.lower():
                    source_chat_id = chat.id
                    break
            if source_chat_id is None:
                print(f"MAX_SOURCE_CHAT_TITLE not found: {source_chat_title}")
            else:
                try:
                    source_chat_id = int(source_chat_id)
                except ValueError:
                    print("MAX_SOURCE_CHAT_ID must be a number")

    @client.on_message()
    async def handle_message(message, client: Client) -> None:
        # Ignore messages from chats other than the source chat
        if source_chat_id is not None and message.chat_id != source_chat_id:
            return
        sender_name = None
        if message.sender: # if the message has a sender get the user details
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
