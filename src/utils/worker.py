import os
import asyncio
import json
import time
import structlog
import tempfile
from io import BytesIO
from datetime import datetime

from core.config import settings
#from core.comfyui_api import ComfyUiAPI
from core.multi_comfyui_api import MultiComfyUiAPI
from core.redis import redis
from utils.sms import send_sms_download_message
from utils.s3 import upload_fileobj, s3_client, create_presigned_download


log = structlog.get_logger()

class Worker:

    def __init__(self, server_list):

        self.api = MultiComfyUiAPI(
            server_list,
            settings.IMAGE_TEMP_FOLDER,
            settings.WORKFLOW_PATH,
            settings.WORKFLOW_NODE_ID_KSAMPLER,
            settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
            settings.WORKFLOW_NODE_ID_TEXT_INPUT
        )
        self.queued_jobs = {}

    def get_earliest_job(self, queued_jobs):
        min_date = None
        min_job_id = None
        for v in queued_jobs.values():
            date = v["created_at"]
            if not min_date or date < min_date:
                min_date = date
                min_job_id = v["job_id"]

        return min_job_id

        def parse_time(job):
            try:
                return datetime.fromisoformat(job["created_at"])
            except Exception:
                return datetime.max  # fallback for malformed dates

        return min(queued_jobs, key=parse_time)

    async def process_one_job(self, request_id, input_path):
        log.info("worker.job_popped", request_id=request_id, input_path=input_path)

        attempt = await redis.hget(f"job:{request_id}", "attempt")
        if not attempt:
            attempt = 1

        # marca como processing
        await redis.hset(f"job:{request_id}", mapping={"status": "processing", "input": input_path, "attempt": attempt})

        obj = s3_client.get_object(Bucket=settings.S3_BUCKET, Key=input_path)
        body = obj["Body"].read()
        bio = BytesIO(body)

        start = time.time()
        try:
            server_address = self.api.get_available_server_address()
            await redis.hset(f"job:{request_id}", mapping={"server": server_address})
            out = self.api.generate_image_buffer(server_address, bio)
        except Exception as e:
            log.error("worker.generate_error", request_id=request_id, error=str(e))
            await redis.hset(f"job:{request_id}", mapping={"status": "failed", "error": str(e)})
            return

        out.seek(0)
        s3_key = upload_fileobj(out, key_prefix=f"output/{request_id}")
        image_url = create_presigned_download(s3_key, expires_in=3600)
        log.info("worker.uploaded_s3", request_id=request_id, s3_key=s3_key)

        duration = time.time() - start
        log.info("worker.job_done", request_id=request_id, duration=duration)

        # atualiza média móvel
        prev_avg = float(await redis.get("avg_processing_time") or duration)
        new_avg = prev_avg * 0.8 + duration * 0.2
        await redis.set("avg_processing_time", new_avg)
        log.info("worker.avg_updated", new_avg=new_avg)

        # grava resultado
        await redis.hset(f"job:{request_id}", mapping={"status": "done", "output": image_url})
        log.info("worker.job_finished", request_id=request_id, image_url=image_url)

        # notifica por SMS se tiver número
        phone = await redis.hget(f"job:{request_id}", "phone")
        if phone:
            sent = send_sms_download_message(image_url, phone)
            log.info("worker.sms_sent", request_id=request_id, phone=phone, success=sent)
            await redis.hset(f"job:{request_id}", "sms_status", "sent" if sent else "failed")
        else:
            log.info("worker.no_phone", request_id=request_id)

    async def check_for_new_jobs(self):
        while True:
            raw = await redis.rpop("submissions_queue")
            if raw is None:
                break
            job = json.loads(raw)
            request_id = job["id"]
            input_path = job["input"]
            now = datetime.utcnow().isoformat()
            await redis.hset(f"job:{request_id}",
                             mapping={"status": "queued", "input": input_path,
                                      "attempt": 1, "enqueued_at": now})

    async def process_jobs(self):
        matching_statuses = {"processing", "queued", "failed"}
        async for key in redis.scan_iter("job:*"):
            job_data = await redis.hgetall(key)
            status = job_data.get("status", b"")
            request_id = key[4:]

            if status in matching_statuses:
                print(f"Job ID: {key}")
                for k, v in job_data.items():
                    print(f"  {k}: {v}")

                if status == "queued":
                    job_id = key
                    if job_id not in self.queued_jobs:
                        created_at = job_data.get(b"created_at", b"")
                        input = job_data.get(b"input", b"")
                        self.queued_jobs[job_id] = ({
                            "job_id": job_id,
                            "created_at": created_at,
                            "input": input
                        })

                elif status == "failed":
                    attempt = job_data["attempt"] + 1
                    if attempt <= 3:
                        await redis.hset(f"job:{request_id}",
                                         mapping={"status": "queued", "attempt": attempt})
                    else:
                        await redis.hset(f"job:{request_id}", mapping={"status": "error"})

                print("-" * 40)

    async def activate_queued_jobs(self):
        # check if there are available servers to process the jobs

        earliest_job_id = self.get_earliest_job(self.queued_jobs)
        if earliest_job_id:
            earliest = self.queued_jobs[earliest_job_id]
            request_id = earliest["job_id"]
            input_path = earliest["input"]
            print(f"Process Job: {request_id} - {input_path}")
            self.queued_jobs.pop(request_id)
            await self.process_one_job(request_id, input_path)


    async def worker_loop(self):
        """
        Loop infinito que consome jobs da fila 'submissions_queue' no Redis,
        processa cada um sequencialmente, atualiza métricas e envia SMS quando
        o usuário tiver registrado um telefone.
        """

        while True:
            await asyncio.sleep(2)

            # checks if there are new jobs
            await self.check_for_new_jobs()

            await self.process_jobs()

            await self.activate_queued_jobs()


