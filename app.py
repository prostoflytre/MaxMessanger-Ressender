import asyncio
import os
import sys
from typing import Iterable
from pymax import Client
import logging

import requests

from pymax import ExtraConfig
from pymax.types import PhotoAttachment, VideoAttachment
from dotenv import load_dotenv

from channel_to_bot import get_tg_message, send_to_telegram

# Output in console
def debug_log(message: str) -> None:
    enabled = os.getenv("MAX_DEBUG", "true").lower() in {"1", "true", "yes"}
    if enabled:
        print(f"[MaxRessend] {message}")

# get env data, with output in console if missing
def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        print(f"Missing required env var: {name}, check .env file")
        sys.exit(2)
    return value

# get message info as a formatted string with reaction info
def format_message_details(message: object, sender_name: str | None = None, id: str | None = None) -> str:
    def safe_get(name: str) -> str:
        value = getattr(message, name, None)
        return "" if value is None else str(value)

    fields = {
        "Отправитель": sender_name or "",
        "ID": id,
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
    print(f"Name object: {name}")
    first_name = getattr(name, "first_name", None)
    last_name = getattr(name, "last_name", None)
    id = getattr(name, "id", None)
    # Combine first and last name if not None, false or empty
    full = " ".join(part for part in [first_name, last_name, id] if part) 
    return full or getattr(name, "name", None)


# Create Client and start it
def build_client() -> Client:
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
        # keep listening forever, restarting the listener if it exits or errors
        while True:
            try:
                await get_tg_message(client=client)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("get_tg_message crashed, restarting")
            await asyncio.sleep(1)

    @client.on_start()
    async def on_start(client: Client) -> None:
        
        tg_message_task = asyncio.create_task(run_max_tg_listener(client=client))
        _background_tasks.add(tg_message_task)
        tg_message_task.add_done_callback(_background_tasks.discard)



    @client.on_message()
    async def handle_message(message, client: Client) -> None:
        sender_name = None
        if message.sender: # if the message has a sender get the user details
            user = await client.get_user(message.sender)
            sender_name = get_user_display_name(user)
        text = message.text or ""
        summary = f"{format_message_details(message, sender_name, id=message.sender)}\nText: {text}"
        await send_to_telegram(summary)



    await client.start()



    await client.idle()


if __name__ == "__main__":
    asyncio.run(main())
