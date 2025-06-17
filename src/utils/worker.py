import os
import json
import time
import structlog
import tempfile
from io import BytesIO

from core.config import settings
from core.comfyui_api import ComfyUiAPI
from core.redis import redis
from utils.sms import send_sms_download_message
from utils.s3 import upload_fileobj, s3_client, create_presigned_download


log = structlog.get_logger()

async def worker_loop():
    """
    Loop infinito que consome jobs da fila 'submissions_queue' no Redis,
    processa cada um sequencialmente, atualiza métricas e envia SMS quando
    o usuário tiver registrado um telefone.
    """
    api = ComfyUiAPI(
        settings.COMFYUI_API_SERVER,
        settings.IMAGE_TEMP_FOLDER,
        settings.WORKFLOW_PATH,
        settings.WORKFLOW_NODE_ID_KSAMPLER,
        settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
        settings.WORKFLOW_NODE_ID_TEXT_INPUT
    )

    while True:
        # bloqueia até receber um job
        _, raw = await redis.brpop("submissions_queue")
        job = json.loads(raw)
        rid = job["id"]
        inp = job["input"]

        log.info("worker.job_popped", request_id=rid, input_key=inp)

        # marca como processing
        await redis.hset(f"job:{rid}", "status", "processing")

        # faz download da imagem de entrada do S3
        obj = s3_client.get_object(Bucket=settings.S3_BUCKET, Key=inp)
        body = obj["Body"].read()
        bio = BytesIO(body)

        start = time.time()
        try:
            # gera um BytesIO com a saída
            out = api.generate_image_buffer(bio)
        except Exception as e:
            err = str(e)
            log.error("worker.generate_error", request_id=rid, error=err)
            await redis.hset(f"job:{rid}", mapping={"status": "error", "error": err})
            continue

        # volta o ponteiro pra leitura
        out.seek(0)

        # envia a saída pra S3
        s3_key = upload_fileobj(out, key_prefix=f"output/{rid}")
        image_url = create_presigned_download(s3_key, expires_in=86400)
        log.info("worker.uploaded_s3", request_id=rid, s3_key=s3_key)

        duration = time.time() - start
        log.info("worker.job_done", request_id=rid, duration=duration)

        # atualiza média móvel
        prev_avg = float(await redis.get("avg_processing_time") or duration)
        new_avg = prev_avg * 0.8 + duration * 0.2
        await redis.set("avg_processing_time", new_avg)
        log.info("worker.avg_updated", new_avg=new_avg)

        # grava resultado final
        await redis.hset(f"job:{rid}", mapping={"status": "done", "output": image_url})
        log.info("worker.job_finished", request_id=rid, image_url=image_url)

        # se tiver telefone, manda SMS síncrono
        phone = await redis.hget(f"job:{rid}", "phone")
        if phone:
            sent = send_sms_download_message(image_url, phone)
            await redis.hset(f"job:{rid}", "sms_status", "sent" if sent else "failed")
            log.info("worker.sms_sent", request_id=rid, phone=phone, success=sent)
        else:
            log.info("worker.no_phone", request_id=rid)
