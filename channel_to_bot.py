import asyncio
import redis.asyncio as aioredis

async def send_to_telegram(message: str) -> None:
    redis_client = aioredis.from_url("redis://localhost")
    await redis_client.publish("max_channel", message)
    await redis_client.close()