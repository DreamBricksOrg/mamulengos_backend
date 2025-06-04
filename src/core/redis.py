from .config import settings
from redis.asyncio import Redis


redis = Redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True
)