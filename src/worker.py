import os
import asyncio
import json
import time
import structlog
import tempfile
from io import BytesIO
from datetime import datetime

from core.config import settings
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
        self.servers_in_use = set()

    def get_earliest_job(self, queued_jobs):
        min_date = None
        min_job_id = None
        for v in queued_jobs.values():
            date = v["created_at"]
            if not min_date or date < min_date:
                min_date = date
                min_job_id = v["job_id"]

        return min_job_id

    async def process_one_job(self, server_address, request_id, input_path):
        log.info("worker.job_popped", server_address=server_address, request_id=request_id, input_path=input_path)

        attempt = await redis.hget(f"job:{request_id}", "attempt")
        if not attempt:
            attempt = 1

        # marca como processing
        now = datetime.now().isoformat()
        await redis.hset(f"job:{request_id}",
                         mapping={"status": "processing",
                                  "input": input_path,
                                  "attempt": attempt,
                                  "proc_start_at": now})

        # faz download da imagem de entrada do S3
        obj = s3_client.get_object(Bucket=settings.S3_BUCKET, Key=input_path)
        body = obj["Body"].read()
        bio = BytesIO(body)

        start = time.time()
        try:
            await redis.hset(f"job:{request_id}", mapping={"server": server_address})
            # Run generate_image_buffer in a background thread
            out = await asyncio.to_thread(self.api.generate_image_buffer, server_address, bio)
        except Exception as e:
            err = str(e)
            log.error("worker.generate_error", request_id=request_id, error=err)
            await redis.hset(f"job:{request_id}", mapping={"status": "failed", "error": err})
            return

        # volta o ponteiro pra leitura
        out.seek(0)

        # envia a saída pra S3
        s3_key = upload_fileobj(out, key_prefix=f"output/{request_id}")
        image_url = create_presigned_download(s3_key, expires_in=86400)
        log.info("worker.uploaded_s3", request_id=request_id, s3_key=s3_key)

        duration = time.time() - start
        log.info("worker.job_done", request_id=request_id, duration=duration)

        # atualiza média móvel
        prev_avg = float(await redis.get("avg_processing_time") or duration)
        new_avg = prev_avg * 0.8 + duration * 0.2
        await redis.set("avg_processing_time", new_avg)
        log.info("worker.avg_updated", new_avg=new_avg)

        # grava resultado final
        await redis.hset(f"job:{request_id}", mapping={"status": "done", "output": image_url})
        log.info("worker.job_finished", request_id=request_id, image_url=image_url)

        # se tiver telefone, manda SMS síncrono
        phone = await redis.hget(f"job:{request_id}", "phone")
        if phone:
            sent = send_sms_download_message(f"https://apostenaquinadesaojoao.com.br/meumamulengo.html?image_id={request_id}", phone)
            await redis.hset(f"job:{request_id}", "sms_status", "sent" if sent else "failed")
            log.info("worker.sms_sent", request_id=request_id, phone=phone, success=sent)
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
        self.servers_in_use.clear()

        async for key in redis.scan_iter("job:*"):
            job_data = await redis.hgetall(key)
            status = job_data.get("status", b"")
            request_id = key[4:]

            if status in matching_statuses:
                log.debug(f"Job ID: {key}")
                for k, v in job_data.items():
                    log.debug(f"  {k}: {v}")

                if status == "queued":
                    if request_id not in self.queued_jobs:
                        created_at = job_data.get("created_at", "")
                        input = job_data.get("input", "")
                        self.queued_jobs[request_id] = ({
                            "job_id": request_id,
                            "created_at": created_at,
                            "input": input
                        })

                elif status == "failed":
                    attempt = int(job_data["attempt"]) + 1
                    if attempt <= 3:
                        await redis.hset(f"job:{request_id}",
                                         mapping={"status": "queued", "attempt": attempt})
                    else:
                        await redis.hset(f"job:{request_id}", mapping={"status": "error"})

                elif status == "processing":
                    server = job_data.get("server", "")
                    self.servers_in_use.add(server)
                    proc_start_at = job_data.get("proc_start_at", "")
                    dt_proc_start_at = datetime.fromisoformat(proc_start_at)
                    duration = datetime.now() - dt_proc_start_at
                    if duration.total_seconds() > 300:
                        await redis.hset(f"job:{request_id}",
                                         mapping={"status": "fail", "error": "Timeout while processing"})

                log.debug("-" * 40)

    async def activate_queued_jobs(self):
        # check if there are available servers to process the jobs

        earliest_job_id = self.get_earliest_job(self.queued_jobs)
        if not earliest_job_id:
            return

        available_servers = await self.api.get_available_server_addresses()

        for available_server in available_servers:
            if available_server in self.servers_in_use:
                continue
            if earliest_job_id:
                earliest = self.queued_jobs[earliest_job_id]
                request_id = earliest["job_id"]
                input_path = earliest["input"]
                log.info(f"Found job to start (request_id:'{request_id}', input_path:'{input_path}')")

                if not input_path:
                    await self.redis.hset(f"job:{request_id}", mapping={"status": "error", "error": "No input path"})
                    continue

                log.debug(f"Process Job: {request_id} - {input_path}")
                self.queued_jobs.pop(request_id)

                # Run process_one_job in a thread
                asyncio.create_task(self.process_one_job(available_server, request_id, input_path))

                earliest_job_id = self.get_earliest_job(self.queued_jobs)
            else:
                break

    async def worker_loop(self):
        """
        Loop infinito que consome jobs da fila 'submissions_queue' no Redis,
        processa cada um sequencialmente, atualiza métricas e envia SMS quando
        o usuário tiver registrado um telefone.
        """

        while True:
            log.debug("sleep")
            await asyncio.sleep(0.5)

            # checks if there are new jobs
            log.debug("check_for_new_jobs")
            await self.check_for_new_jobs()

            log.debug("process_jobs")
            await self.process_jobs()

            log.debug("activate_queued_jobs")
            await self.activate_queued_jobs()

            log.debug("=" * 40)


if __name__ == "__main__":
    """
    Inicia o worker_loop em paralelo ao servidor.
    """
    server_list = [settings.COMFYUI_API_SERVER, settings.COMFYUI_API_SERVER2,
                   settings.COMFYUI_API_SERVER3, settings.COMFYUI_API_SERVER4]

    worker = Worker(server_list)

    log.info("worker.startup")
    asyncio.run(worker.worker_loop())