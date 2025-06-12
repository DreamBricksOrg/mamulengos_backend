import json
import time
import structlog

from core.config import settings
from core.comfyui_api import ComfyUiAPI
from core.redis import redis
from utils.sms import send_sms_download_message


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

        log.info("worker.job_popped", request_id=rid, input_path=inp)

        # marca como processing
        await redis.hset(f"job:{rid}", mapping={"status":"processing", "input":inp})

        start = time.time()
        try:
            out = api.generate_image(inp)
        except Exception as e:
            log.error("worker.generate_error", request_id=rid, error=str(e))
            # opcional: marque status de erro
            await redis.hset(f"job:{rid}", mapping={"status":"error", "error":str(e)})
            continue

        duration = time.time() - start
        log.info("worker.job_done", request_id=rid, duration=duration)

        # atualiza média móvel
        prev_avg = float(await redis.get("avg_processing_time") or duration)
        new_avg = prev_avg * 0.8 + duration * 0.2
        await redis.set("avg_processing_time", new_avg)
        log.info("worker.avg_updated", new_avg=new_avg)

        # grava resultado
        await redis.hset(f"job:{rid}", mapping={"status":"done", "output":out})

        # notifica por SMS se tiver número
        phone = await redis.hget(f"job:{rid}", "phone")
        if phone:
            link = f"{settings.BASE_URL}/result/{rid}"
            sent = send_sms_download_message(link, phone)
            log.info("worker.sms_sent", request_id=rid, phone=phone, success=sent)
        else:
            log.info("worker.no_phone", request_id=rid)
