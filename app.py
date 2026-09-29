"""Max client entry point and attachment forwarding handlers."""

import asyncio
import json
import os, gzip
import sys
from pymax import Client, Message
import logging

import ssl
from pathlib import Path
import aiohttp
import aiohttp.connector as _aiohttp_connector
import certifi
from pymax import ExtraConfig
from pymax.types import PhotoAttachment, VideoAttachment, AudioAttachment, StickerAttachment, FileAttachment
from dotenv import load_dotenv
from debug import debug_log


from channel_to_bot import get_tg_message, send_to_telegram

# aiohttp builds its default SSL context from the Windows cert store at import time,
# which can lack the CA chain for some hosts (e.g. omu.okcdn.ru) and raise
# CERTIFICATE_VERIFY_FAILED. Force it to use certifi's bundle instead, since pymax
# creates its own aiohttp.ClientSession() internally with no way to inject ssl=.
_aiohttp_connector._SSL_CONTEXT_VERIFIED = ssl.create_default_context(cafile=certifi.where())


# get env data, with output in console if missing
def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    """Read an environment variable and exit when a required value is missing."""
    value = os.getenv(name, default)
    if required and not value:
        debug_log(f"Missing required env var: {name}, check .env file")
        sys.exit(2)
    return value

async def download_url(url: str, destination: Path) -> None:
    """Download a URL to a local file using streamed response chunks."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()

            with destination.open("wb") as file:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    file.write(chunk)

    debug_log(f"Saved: {destination}")

async def download_message_attachments(
    message: Message,
    client: Client,
    output_dir: str = "downloads",
) -> dict:
    """Download message attachments and return their local paths by type."""
    if message.chat_id is None:
        debug_log("У сообщения нет chat_id — получить URL видео/файла нельзя.")
        return {}

    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)  # Added to ensure output directory exists
    
    attach_list = [attach for attach in message.attaches]
    
    # Initialize keys as lists so we can append multiple attachments of the same type
    path_list = {
        "photo": [],
        "audio": [],
        "sticker": [],
        "sticker_emoji": [],
        "video": [],
        "file": []
    }

    for index, attach in enumerate(attach_list):
        debug_log(f'attach: {attach}')
        # Photo handler
        if isinstance(attach, PhotoAttachment):
            path = folder / f"photo_{attach.photo_id}.jpg"
            debug_log(f"Downloading photo {attach.photo_id}: {attach.base_url}")
            await download_url(attach.base_url, path)
            path_list["photo"].append(str(path.resolve()))

        # Audio handler
        elif isinstance(attach, AudioAttachment):
            path = folder / f"audio_{attach.audio_id}.ogg"
            debug_log(f"Downloading audio {attach.audio_id}: {attach.url}")
            await download_url(attach.url, path)
            path_list["audio"].append(str(path.resolve()))

        # Sticker handler
        elif isinstance(attach, StickerAttachment):
            if attach.lottie_url is not None:
                path = folder / f"sticker_{attach.sticker_id}.tgs"
                debug_log(f"Downloading sticker {attach.sticker_id}: {attach.lottie_url}")
                await download_url(attach.lottie_url, path)
                
                try:
                    with open(path, "rb") as f_in:
                        file_content = f_in.read()
                    if not file_content.startswith(b"\x1f\x8b"):
                        debug_log(f"File {path} is not a valid gzip file.")
                        with gzip.open(path, "wb") as f_out:
                            f_out.write(file_content)
                except Exception as e:
                    debug_log(f"Failed to compress sticker {attach.sticker_id}: {e}")
                
                path_list["sticker"].append(str(path.resolve()))
            else:
                sticker = "".join(attach.tags or [])
                path_list["sticker_emoji"].append(sticker)
                debug_log(f"Sticker without lottie_url: {sticker}")

        # Video handler
        elif isinstance(attach, VideoAttachment):
            video_info = await client.get_video_by_id(
                chat_id=message.chat_id,
                message_id=message.id,
                video_id=attach.video_id,
            )
            if video_info is None:
                debug_log(f"Video URL was not returned for video_id={attach.video_id}")
                continue
            if video_info.url:
                path = folder / f"video_{attach.video_id}.mp4"
                debug_log(f"Downloading video {attach.video_id}: {video_info.url}")
                await download_url(video_info.url, path)
                path_list["video"].append(str(path.resolve()))
            elif video_info.external:
                debug_log(f"Video {attach.video_id} is external; source: {video_info.external}")

        # File handler
        elif isinstance(attach, FileAttachment):
            file_info = await client.get_file_by_id(
                chat_id=message.chat_id,
                message_id=message.id,
                file_id=attach.file_id,
            )
            if file_info is None:
                debug_log(f"File URL was not returned for file_id={attach.file_id}")
                continue
            
            filename = Path(attach.name).name or f"file_{attach.file_id}"
            path = folder / filename
            debug_log(f"Downloading file {attach.file_id}: {file_info.url}")
            await download_url(file_info.url, path)
            path_list["file"].append(str(path.resolve()))

    # Optional: Clean up empty lists from the response dictionary
    return {key: value for key, value in path_list.items() if value}


# get user display name from message
def get_user_display_name(user: object | None) -> str:
    """Return the first available display name from a Max user object."""
    if not user:
        return ""
    for name in user.names:
        if name.name:
            return name.name
        parts = [p for p in (name.first_name, name.last_name) if p]
        if parts:
            return " ".join(parts)
    return ""


# Create Client and start it
def build_client() -> Client:
    """Create a Max client from the configured account and device settings."""
    phone = get_env("MAX_PHONE")
    session_name = get_env("MAX_SESSION", default="session.db")
    token = get_env("MAX_TOKEN", required=False)
    work_dir = get_env("MAX_WORK_DIR", default=".")
    device_type = get_env("MAX_DEVICE_TYPE", default="DESKTOP")

    client = Client(
        phone=phone,
        session_name=session_name,
        work_dir=work_dir,
        extra_config=ExtraConfig(token=token, device_type=device_type),
    )

    return client


# Entry point for the application
async def main() -> None:
    """Start the Max client and relay incoming messages to Telegram."""

    # Load environment variables from .env file
    load_dotenv()
    """ 
    Инициализация Telegram бота
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    bot = TeleBot(bot_token)
    """

    client = build_client()

    _background_tasks: set[asyncio.Task] = set()


    async def run_max_tg_listener(client: Client) -> None:
        """Keep the Telegram message listener running and restart on errors."""
        # keep listening forever, restarting the listener if it exits or errors
        while True:
            try:
                await get_tg_message(client=client)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("get_tg_message crashed, restarting")
            await asyncio.sleep(1)

    tg_listener_task: asyncio.Task | None = None

    @client.on_start()
    async def on_start(client: Client) -> None:
        """Start the Redis-to-Max listener once; pymax fires on_start on every reconnect too."""
        nonlocal tg_listener_task
        if tg_listener_task is not None and not tg_listener_task.done():
            return

        tg_listener_task = asyncio.create_task(run_max_tg_listener(client=client))
        _background_tasks.add(tg_listener_task)
        tg_listener_task.add_done_callback(_background_tasks.discard)


    @client.on_message()
    async def handle_message(message: Message, client: Client) -> None:
        """Serialize a Max message and publish it for Telegram delivery."""
        sender_name = None
        if message.sender: # if the message has a sender get the user details
            user = await client.get_user(message.sender)
            sender_name = get_user_display_name(user)
        text = message.text or ""
        if text in ["Василиса,  отправь плиз в чат. Спс", "Василиса, отправь плиз в общий чат! Спасибо", "Не все еще зашли в Приложение МЭШ Колледж! Заходим пожалуйста", "👍"]:
            return
        summary = {
            "message": str(message),
            "sender": sender_name,
            "id": message.sender,
            "text": text
        }
        if message.attaches:
            media : dict = await download_message_attachments(message=message, client=client)
            summary.update({"media": media})
        summary = json.dumps(summary, ensure_ascii=False)
        await send_to_telegram(summary)


    try:
        await client.start()
        await client.idle()
    except RuntimeError as error:
        if "Failed to dispatch inbound frame" in str(error):
            logging.error(f"Обнаружен критический баг валидации библиотеки: {error}")
            logging.error("Вызываем принудительное завершение процесса. Systemd чисто перезапустит службу.")
            
            for task in _background_tasks:
                task.cancel()
            await asyncio.sleep(1)  # Give cancelled tasks a chance to exit gracefully
            import sys
            sys.exit(1)
        else:

            raise error
    except Exception as error:
        logging.exception(f"Непредвиденная критическая ошибка приложения: {error}")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
