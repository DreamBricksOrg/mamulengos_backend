import structlog
import uuid
import os
import json

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from core.config import settings

from core.comfyui_api import ComfyUiAPI
from core.redis import redis
from utils.sms import format_to_e164
from utils.files import generate_timestamped_filename


log = structlog.get_logger()

router = APIRouter()
BASE_DIR = os.path.dirname(__file__) 
TEMPLATES_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend", "templates"))
templates = Jinja2Templates(directory=TEMPLATES_DIR)
UPLOAD_FOLDER = settings.IMAGE_TEMP_FOLDER

api = ComfyUiAPI(
    settings.COMFYUI_API_SERVER,
    UPLOAD_FOLDER,
    settings.WORKFLOW_PATH,
    settings.WORKFLOW_NODE_ID_KSAMPLER,
    settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
    settings.WORKFLOW_NODE_ID_TEXT_INPUT,
)


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
    image: UploadFile = File(...)
):
    if image.filename == "":
        raise HTTPException(400, "Nome de arquivo inválido")

    rid = str(uuid.uuid4())

    filename = generate_timestamped_filename(settings.IMAGE_TEMP_FOLDER, f"mamulengos_in_{rid}", "jpg")
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    content = await image.read()
    with open(filename, "wb") as f:
        f.write(content)

    payload = {
        "id": rid,
        "input": filename
    }
    await redis.lpush("submissions_queue", json.dumps(payload))

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
        # opcional: envie também a mensagem de erro registrada
        return JSONResponse({"status": "error", "error": data.get("error")})

    if status == "done":
        output_path = data.get("output")
        if not output_path or not os.path.isfile(output_path):
            raise HTTPException(status_code=500, detail="Imagem processada mas arquivo não encontrado")

        # gera a URL pública; ajuste se servir de outro lugar
        rel = os.path.relpath(output_path, settings.STATIC_DIR).replace("\\", "/")
        image_url = f"{settings.BASE_URL}/static/{rel}"
        return JSONResponse({"status": "done", "image_url": image_url})

    # se ainda não marcou como "processing"/"done"/"error", considera em fila
    return JSONResponse({"status": "queued"})

@router.post("/api/notify")
async def register_notification(request_id: str, phone: str):
    # registra telefone para notificação pós-processamento
    if not await redis.exists(f"job:{request_id}"):
        raise HTTPException(404, "Request ID não encontrado")
    await redis.hset(f"job:{request_id}", "phone", format_to_e164(phone))
    return JSONResponse({"status": "PHONE_REGISTERED"})


@router.get("/error")
async def error(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})
