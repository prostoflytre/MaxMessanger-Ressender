import asyncio
import os
import json
import redis.asyncio as aioredis
from tg_integration import send_message_from_tg
from debug import debug_log, debug_channels
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()
redis_url = os.getenv("REDIS_URL")
tg_channel = "tg_channel"
max_channel = "max_channel"
if debug_channels(): 
    tg_channel += "_debug"
    max_channel += "_debug"

async def send_to_telegram(message: str) -> None:
    redis_client = aioredis.from_url(redis_url)
    await redis_client.publish(max_channel, message)
    debug_log(f"Published message to {max_channel}: {message}")
    await redis_client.close()

async def get_tg_message(client) -> None:
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(tg_channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    message_data = json.loads(message['data'])
                    recipient_chat = message_data["recipient_chat"]
                    message_text = message_data["text"]
                    media = message_data.get("media")
                    if not isinstance(message_text, str):
                        raise ValueError("message must be a string")
                    await send_message_from_tg(recipient_chat, media, message_text, client)
                    debug_log(f"Received message from {tg_channel}: {message['data']}")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    debug_log(f"Invalid message from {tg_channel}: {error}")
                except Exception as error:
                    debug_log(f"Unable to forward message from {tg_channel}: {error}")
    finally:
        await pubsub.unsubscribe(tg_channel)
        await pubsub.aclose()
        await redis_client.close()