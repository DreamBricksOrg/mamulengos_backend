import structlog
import uuid
import os
import json
from io import BytesIO
import asyncio


from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import BackgroundTasks

from core.config import settings

from core.redis import redis
from utils.sms import format_to_e164, send_sms_download_message
from utils.s3 import upload_fileobj


router = APIRouter()
log = structlog.get_logger()

BASE_DIR = os.path.dirname(__file__) 
TEMPLATES_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend", "templates"))
templates = Jinja2Templates(directory=TEMPLATES_DIR)

async def enqueue_job(rid: str, input_key: str):
    payload = {"id": rid, "input": input_key}
    await redis.lpush("submissions_queue", json.dumps(payload))

async def send_sms_task(request_id: str, image_url: str, phone: str):
    sent = await asyncio.to_thread(send_sms_download_message, image_url, phone)
    log.info("notify.immediate_sms", request_id=request_id, phone=phone, success=sent)
    await redis.hset(f"job:{request_id}", "sms_status", "sent" if sent else "failed")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, image_url: str = None):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "image_url": image_url
    })


@router.get("/alive")
async def alive():
    return "Alive"

@router.post("/api/upload")
async def upload(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
):
    if not image.filename:
        raise HTTPException(400, "Nome de arquivo inválido")

    rid = str(uuid.uuid4())
    key = f"job:{rid}"
    await redis.hset(key, mapping={
        "status": "queued",
        "input": "",
        "output": "",
    })

    content = await image.read()
    bio = BytesIO(content)
    input_key = upload_fileobj(bio, key_prefix=f"input/{rid}")

    await redis.hset(key, "input", input_key)

    background_tasks.add_task(enqueue_job, rid, input_key)

    pos = await redis.llen("submissions_queue")
    avg = float(await redis.get("avg_processing_time") or 80)
    eta = int(pos) * avg

    return JSONResponse({
        "status": "QUEUED",
        "request_id": rid,
        "position_in_queue": pos,
        "estimated_wait_seconds": eta
    })

@router.get("/api/result")
async def get_result(request_id: str = Query(...)):
    key = f"job:{request_id}"
    exists = await redis.exists(key)
    if not exists:
        raise HTTPException(status_code=404, detail="Request ID não encontrado")

    data = await redis.hgetall(key)
    status = data.get("status")

    if status == "processing":
        return JSONResponse({"status": "processing"})

    if status == "error":
        return JSONResponse({"status": "error", "error": data.get("error")})

    if status == "done":
        image_url = data.get("output")
        if not image_url:
            raise HTTPException(status_code=500, detail="Imagem processada mas arquivo não encontrado")
        return JSONResponse({"status": "done", "image_url": image_url})

    # se ainda não marcou como "processing"/"done"/"error", considera em fila
    return JSONResponse({"status": "queued"})

@router.post("/api/notify")
async def register_notification(
    background_tasks: BackgroundTasks,
    request_id: str = Form(...),
    phone: str = Form(...),
):
    key = f"job:{request_id}"
    if not await redis.exists(key):
        raise HTTPException(404, "Request ID não encontrado")

    formatted = format_to_e164(phone)
    await redis.hset(key, "phone", formatted)

    data = await redis.hgetall(key)
    if data.get("status") == "done":
        image_url = data["output"]
        # agenda o envio de SMS sem bloquear o request
        background_tasks.add_task(send_sms_task, request_id, image_url, formatted)

    return JSONResponse({"status": "PHONE_REGISTERED"})

@router.get("/error")
async def error(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})
