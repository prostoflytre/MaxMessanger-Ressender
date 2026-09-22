import asyncio
import json
import redis.asyncio as aioredis
from tg_integration import send_message_from_tg

async def send_to_telegram(message: str) -> None:
    redis_client = aioredis.from_url("redis://:Mandar1nka!@127.0.0.1:6379?protocol=3")
    await redis_client.publish("max_channel", message)
    print(f"Published message to max_channel: {message}")
    await redis_client.close()

async def get_tg_message(client) -> None:
    redis_client = aioredis.from_url("redis://:Mandar1nka!@127.0.0.1:6379?protocol=3", decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("tg_channel")
    try:
        async for message in pubsub.listen():
            print(message)
            if message["type"] == "message":
                try:
                    message_data = json.loads(message['data'])
                    chat_recipient = message_data["chat_recepient"]
                    message_text = message_data["message"]
                    if not isinstance(message_text, str):
                        raise ValueError("message must be a string")
                    await send_message_from_tg(chat_recipient, message_text, client)
                    print(f"Received message from tg_channel: {message['data']}")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    print(f"Invalid message from tg_channel: {error}")
                except Exception as error:
                    print(f"Unable to forward message from tg_channel: {error}")
    finally:
        await pubsub.unsubscribe("tg_channel")
        await pubsub.aclose()
        await redis_client.close()