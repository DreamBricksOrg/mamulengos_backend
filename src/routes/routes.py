# src/routes/routes.py

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import status
from starlette.responses import FileResponse

from core.config import settings
from core.udp_sender import UDPSender
from utils.qrcode import generate_qr_code

import uuid
import os
import random
import shutil
import threading

router = APIRouter()
templates = Jinja2Templates(directory="templates")

valid_links = {}
MAX_LINKS = 5
IMAGE_BASE_FOLDER = os.path.join("static", "download_images")

@router.get("/cta")
async def cta_get(request: Request):
    return templates.TemplateResponse("cta.html", {"request": request})

@router.post("/cta")
async def cta_post():
    return RedirectResponse(url="/terms", status_code=status.HTTP_302_FOUND)

@router.get("/generateqr")
async def generate_qr():
    if len(valid_links) >= MAX_LINKS:
        valid_links.clear()

    link_id = str(uuid.uuid4())
    link = f"{settings.BASE_URL}/terms?link_id={link_id}"
    valid_links[link_id] = True

    img_bytes = generate_qr_code(link)
    return StreamingResponse(img_bytes, media_type="image/png")

@router.get("/qrcode-images")
async def qrcode_images(request: Request, cod: str = Query(..., description="Código para gerar QR")):
    if not cod:
        raise HTTPException(status_code=400, detail="O parâmetro 'cod' é obrigatório.")

    url = f"{settings.BASE_URL}/show_images/{cod}"
    img_bytes = generate_qr_code(url)

    # Em vez de usar socket_manager direto, pega de request.app.state
    socket_manager = request.app.state.socket_manager
    await socket_manager.emit('render_images', {'cod': cod}, room=cod, namespace='/')

    return StreamingResponse(img_bytes, media_type="image/png")

@router.get("/download-images")
async def download_images(cod: str = Query(..., description="Código da pasta")):
    folder_path = os.path.join(IMAGE_BASE_FOLDER, cod)
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=404, detail="Folder not found.")

    image_files = [
        f for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
    ]
    if not image_files:
        raise HTTPException(status_code=404, detail="No images found.")

    image_urls = [
        f"{settings.BASE_URL}/images/{cod}/{image}"
        for image in image_files
    ]
    return JSONResponse(content=image_urls)

@router.get("/images/{cod}/{filename}")
async def serve_image(cod: str, filename: str):
    folder_path = os.path.join(IMAGE_BASE_FOLDER, cod)
    file_path = os.path.join(folder_path, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Image not found.")

    return FileResponse(path=file_path, media_type="image/jpeg", filename=filename)

@router.get("/show_images/{cod}")
async def show_images(request: Request, cod: str):
    images_dir = os.path.join("static", "download_images", cod)
    if not os.path.isdir(images_dir):
        raise HTTPException(status_code=404, detail="Pasta não existe.")

    image_files = [
        f for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
    ]
    image_paths = [
        f"/static/download_images/{cod}/{im}"
        for im in image_files
    ]

    udp_sender = UDPSender(port=settings.UDP_PORT)
    udp_sender.send(f"SCAN:{cod}\n")

    return templates.TemplateResponse(
        "download-images.html",
        {"request": request, "image_paths": image_paths, "cod": cod}
    )

@router.get("/show_images_carousel/{cod}")
async def show_images_carousel(request: Request, cod: str):
    images_dir = os.path.join("static", "download_images", cod)
    if not os.path.isdir(images_dir):
        raise HTTPException(status_code=404, detail="Pasta não existe.")

    image_files = [
        f for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
    ]
    image_paths = [
        f"/static/download_images/{cod}/{im}"
        for im in image_files
    ]

    return templates.TemplateResponse(
        "download-images-carousel.html",
        {"request": request, "image_paths": image_paths, "cod": cod}
    )

@router.get("/terms")
async def terms(request: Request):
    timer = settings.TIMER_TERMS
    return templates.TemplateResponse("terms.html", {"request": request, "timer": timer})

@router.post("/accept")
async def accept():
    random_number = random.randint(1, 99999)
    udp_sender = UDPSender(port=settings.UDP_PORT)
    udp_sender.send(f"INI:{random_number:05d}\n")
    return RedirectResponse(url=f"/play/{random_number}", status_code=status.HTTP_302_FOUND)

@router.get("/play/{cod}")
async def play(request: Request, cod: str):
    return templates.TemplateResponse("play.html", {"request": request, "cod": cod})

@router.get("/ai/{path_to_image:path}")
async def generate_ai(path_to_image: str):
    config_idx = settings.CONFIG_INDEX
    path_to_image = path_to_image.replace("@", "\\")

    if not os.path.isfile(path_to_image):
        return JSONResponse(content={"detail": "ERROR"}, status_code=404)

    def process_image():
        photo = os.path.basename(path_to_image)
        out_image_filename = ComfyUiAPI(
            settings.COMFYUI_API_SERVER,
            settings.IMAGE_TEMP_FOLDER,
            settings.WORKFLOW_PATH,
            settings.WORKFLOW_NODE_ID_KSAMPLER,
            settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
            settings.WORKFLOW_NODE_ID_TEXT_INPUT,
        ).generate_image(path_to_image)

        out_photo = f"cfg{config_idx:02d}_{photo.replace('.jpg', '.png')}"
        move_to = os.path.join(os.path.dirname(path_to_image), out_photo)
        shutil.copy(out_image_filename, move_to)

        udp = UDPSender(port=settings.UDP_PORT)
        udp.send(f"GENERATED:{move_to}\n")

    threading.Thread(target=process_image, daemon=True).start()
    return JSONResponse(content={"status": "PROCESSING"})

@router.get("/error")
async def error(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})
