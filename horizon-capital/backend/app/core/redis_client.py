"""Redis connection pool (aioredis via redis-py async)."""

import redis.asyncio as aioredis

from app.config import settings

redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=50,
    decode_responses=True,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> aioredis.Redis:
    return redis_client


async def close_redis() -> None:
    await redis_pool.disconnect()
