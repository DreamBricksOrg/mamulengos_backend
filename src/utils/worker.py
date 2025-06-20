import os
import asyncio
import json
import time
import structlog
import tempfile
from io import BytesIO

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

    async def process_job(self, request_id, input_path):
        log.info("worker.job_popped", request_id=request_id, input_path=input_path)

        # marca como processing
        await redis.hset(f"job:{request_id}", mapping={"status": "processing", "input": input_path})

        obj = s3_client.get_object(Bucket=settings.S3_BUCKET, Key=input_path)
        body = obj["Body"].read()
        bio = BytesIO(body)

        start = time.time()
        try:
            server_address = self.api.get_available_server_address()
            out = self.api.generate_image_buffer(server_address, bio)
        except Exception as e:
            log.error("worker.generate_error", request_id=request_id, error=str(e))
            await redis.hset(f"job:{request_id}", mapping={"status": "error", "error": str(e)})
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


    async def worker_loop(self):
        """
        Loop infinito que consome jobs da fila 'submissions_queue' no Redis,
        processa cada um sequencialmente, atualiza métricas e envia SMS quando
        o usuário tiver registrado um telefone.
        """

        while True:
            await asyncio.sleep(0.5)

            # checks if there are new jobs
            while True:
                raw = await redis.rpop("submissions_queue")
                if raw is None:
                    break
                job = json.loads(raw)
                request_id = job["id"]
                input_path = job["input"]
                await redis.hset(f"job:{request_id}", mapping={"status": "queued", "input": input_path})

            matching_statuses = {"processing", "queued", "error"}

            async for key in redis.scan_iter("job:*"):
                job_data = await redis.hgetall(key)
                status = job_data.get("status", b"")
                if status in matching_statuses:
                    print(f"Job ID: {key}")
                    for k, v in job_data.items():
                        print(f"  {k}: {v}")
                    print("-" * 40)

                    if status == "queued":
                        request_id = key[4:]
                        input_path = job_data["input"]
                        self.process_job(request_id, input_path)

