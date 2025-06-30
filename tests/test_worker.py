import asyncio
from datetime import datetime, timedelta
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# Set minimal environment variables required by the settings module before
# importing the worker module.
os.environ.setdefault("BASE_URL", "http://testserver")
os.environ.setdefault("STATIC_DIR", "static")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("S3_BUCKET", "dummy-bucket")
os.environ.setdefault("COMFYUI_API_SERVER1", "http://localhost")
os.environ.setdefault("COMFYUI_API_SERVER2", "http://localhost")
os.environ.setdefault("COMFYUI_API_SERVER3", "http://localhost")
os.environ.setdefault("COMFYUI_API_SERVER4", "http://localhost")
os.environ.setdefault("TIMER_TERMS", "20")
os.environ.setdefault("CONFIG_INDEX", "6")

import worker as worker_module


class DummyAPI:
    async def get_available_server_addresses(self):
        return []


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def hset(self, key, mapping=None, **kwargs):
        data = self.store.setdefault(key, {})
        if mapping:
            data.update(mapping)
        if kwargs:
            data.update(kwargs)

    async def hget(self, key, field):
        return self.store.get(key, {}).get(field)

    async def hgetall(self, key):
        return self.store.get(key, {}).copy()

    async def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k

    async def rpop(self, key):
        return None

    async def set(self, key, value):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)


@pytest.mark.usefixtures("monkeypatch")
def test_timeout_sets_failed_status(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(worker_module, "redis", fake)
    monkeypatch.setattr(worker_module, "MultiComfyUiAPI", lambda *args, **kwargs: DummyAPI())

    worker = worker_module.Worker(server_list=[])

    async def run_test():
        start_time = (datetime.utcnow() - timedelta(seconds=301)).isoformat()
        await fake.hset("job:test", mapping={"status": "processing", "proc_start_at": start_time, "server": "srv", "attempt": "1"})
        await worker.process_jobs()
        return await fake.hget("job:test", "status")

    status = asyncio.run(run_test())
    assert status == "failed"
