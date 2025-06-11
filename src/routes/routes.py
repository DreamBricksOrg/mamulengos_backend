import structlog
import uuid
import os
import json

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from core.config import settings

from core.comfyui_api import ComfyUiAPI
from core.redis import redis
from utils.sms import format_to_e164


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

@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    choice: str = Form("king")
):
    if file.filename == "":
        raise HTTPException(400, "Nome de arquivo inválido")

    is_king = (choice == "king")

    rid = str(uuid.uuid4())
    folder = os.path.join(settings.IMAGE_TEMP_FOLDER, rid)
    os.makedirs(folder, exist_ok=True)
    input_path = os.path.join(folder, "input.png")
    with open(input_path, "wb") as f:
        f.write(await file.read())

    payload = {
        "id": rid,
        "input": input_path,
        "is_king": is_king
    }
    await redis.lpush("submissions_queue", json.dumps(payload))

    pos = await redis.llen("submissions_queue")
    avg = float(await redis.get("avg_processing_time") or settings.DEFAULT_PROCESSING_TIME)
    eta = int(pos) * avg

    return JSONResponse({
        "status": "QUEUED",
        "request_id": rid,
        "position_in_queue": pos,
        "estimated_wait_seconds": eta
    })


@router.post("/notify")
async def register_notification(request_id: str, phone: str):
    # registra telefone para notificação pós-processamento
    if not await redis.exists(f"job:{request_id}"):
        raise HTTPException(404, "Request ID não encontrado")
    await redis.hset(f"job:{request_id}", "phone", format_to_e164(phone))
    return JSONResponse({"status": "PHONE_REGISTERED"})


@router.get("/error")
async def error(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})
