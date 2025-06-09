# src/routes/routes.py

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import status
from starlette.responses import FileResponse

from core.config import settings
from core.udp_sender import UDPSender
from utils.qrcode import generate_qr_code
from core.comfyui_api import ComfyUiAPI
from utils.files import (
    generate_timestamped_filename,
    count_files_with_extension,
    count_files_by_hour,
    read_last_n_lines,
    generate_file_activity_plot_base64
)

import uuid
import os
import random
import shutil
import threading

router = APIRouter()
BASE_DIR = os.path.dirname(__file__) 
TEMPLATES_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend", "templates"))
templates = Jinja2Templates(directory=TEMPLATES_DIR)

valid_links = {}
MAX_LINKS = 5
IMAGE_BASE_FOLDER = os.path.join("static", "download_images")

api = ComfyUiAPI(
    settings.COMFYUI_API_SERVER,
    settings.IMAGE_TEMP_FOLDER,
    settings.WORKFLOW_PATH,
    settings.WORKFLOW_NODE_ID_KSAMPLER,
    settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
    settings.WORKFLOW_NODE_ID_TEXT_INPUT,
)

UPLOAD_FOLDER = settings.IMAGE_TEMP_FOLDER

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, image_url: str = None):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "image_url": image_url
    })

@router.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    choice: str = Form("king")
):
    if file.filename == "":
        raise HTTPException(400, "Nome de arquivo inválido")

    is_king = choice == "king"
    rid = str(uuid.uuid4())
    filename = generate_timestamped_filename(UPLOAD_FOLDER, f"kingsday_in_{rid}", "jpg")
    input_path = os.path.join(UPLOAD_FOLDER, filename)

    os.makedirs(os.path.dirname(input_path), exist_ok=True)
    with open(input_path, "wb") as f:
        f.write(await file.read())

    # processamento síncrono (se demorar muito, mover para BackgroundTasks ou fila)
    result_path = api.generate_image(input_path, is_king=is_king)

    rel = os.path.relpath(result_path, "static").replace("\\", "/")
    image_url = f"/static/{rel}"

    return JSONResponse({
        "message": "Imagem processada com sucesso",
        "image_url": image_url
    })

@router.get("/stats", response_class=HTMLResponse)
async def stats(request: Request):
    output_dir = os.path.join("static", "outputs")
    total_files = count_files_with_extension(output_dir, "png")
    activity = count_files_by_hour(output_dir)
    graph_base64 = generate_file_activity_plot_base64(activity, style="plot")

    return templates.TemplateResponse("stats.html", {
        "request": request,
        "total_files": total_files,
        "graph_base64": graph_base64
    })

@router.get("/error")
async def error(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})
