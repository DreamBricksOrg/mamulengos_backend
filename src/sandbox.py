#from core.config import settings
import asyncio
import redis.asyncio as Redis
#from core.redis import redis

from datetime import datetime


# Function 1: Get all queued jobs
async def get_queued_jobs(redis_url="redis://localhost"):
    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    queued_jobs = {}

    async for key in redis.scan_iter("job:*"):
        job_data = await redis.hgetall(key)
        status = job_data.get(b"status", b"")
        if status == "queued":
            job_id = key
            created_at = job_data.get(b"created_at", b"")
            input = job_data.get(b"input", b"")
            queued_jobs[job_id] = ({
                "job_id": job_id,
                "created_at": created_at,
                "input": input
            })

    return queued_jobs


# Function 2: Return the job with the earliest created_at timestamp
def get_earliest_job(queued_jobs):
    if not queued_jobs:
        return None

    def parse_time(job):
        try:
            return datetime.fromisoformat(job["created_at"])
        except Exception:
            return datetime.max  # fallback for malformed dates

    return min(queued_jobs, key=parse_time)


async def print_active_jobs(redis_url="redis://localhost"):
    #r = redis.from_url(redis_url)
    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    matching_statuses = {"processing", "queued", "error"}

    async for key in redis.scan_iter("job:*"):
        job_data = await redis.hgetall(key)
        status = job_data.get("status", b"")
        if status in matching_statuses:
            print(f"Job ID: {key[4:]}")
            for k, v in job_data.items():
                print(f"  {k}: {v}")
            print("-" * 40)
            if status == "error":
                await redis.hset(f"{key}", mapping={"status": "done_error"})
                # , "input": job_data["input"], "error": job_data["error"]


async def show_earliest_job():
    jobs = await get_queued_jobs()
    earliest = get_earliest_job(jobs)
    if earliest:
        print("Earliest job:", earliest["job_id"])
        print("Created at:", earliest["created_at"])
        print("Full data:", earliest["raw_data"])
    else:
        print("No queued jobs found.")


# Run the function
if __name__ == "__main__":
    #asyncio.run(print_active_jobs())
    asyncio.run(show_earliest_job())
