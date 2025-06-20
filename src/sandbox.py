#from core.config import settings
import asyncio
import redis.asyncio as Redis
#from core.redis import redis

async def print_active_jobs(redis_url="redis://localhost"):
    #r = redis.from_url(redis_url)
    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    matching_statuses = {"processing", "queued", "error"}

    async for key in redis.scan_iter("job:*"):
        job_data = await redis.hgetall(key)
        status = job_data.get("status", b"")
        if status not in matching_statuses:
            print(f"Job ID: {key[4:]}")
            for k, v in job_data.items():
                print(f"  {k}: {v}")
            print("-" * 40)
            if status == "error":
                await redis.hset(f"{key}", mapping={"status": "done_error"})
                # , "input": job_data["input"], "error": job_data["error"]

# Run the function
if __name__ == "__main__":
    asyncio.run(print_active_jobs())
