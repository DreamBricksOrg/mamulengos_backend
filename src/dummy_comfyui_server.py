import os
import io
import asyncio
from uuid import uuid4
from typing import Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Response
from PIL import Image, ImageDraw

PROCESSING_DELAY = float(os.getenv("DEFAULT_PROCESSING_TIME", "1000")) / 1000.0

app = FastAPI()

uploaded_images: Dict[str, bytes] = {}
jobs: Dict[str, Dict[str, Any]] = {}
websockets: Dict[str, WebSocket] = {}
queue_running: bool = False


@app.post("/upload/image")
async def upload_image(image: UploadFile = File(...), subfolder: str = Form(""), overwrite: str = Form("false")):
    content = await image.read()
    filename = f"{uuid4().hex}.png"
    uploaded_images[filename] = content
    return {"name": filename, "subfolder": subfolder}


@app.post("/prompt")
async def prompt_endpoint(payload: Dict[str, Any]):
    prompt = payload.get("prompt", {})
    client_id = payload.get("client_id")
    prompt_id = uuid4().hex

    image_path = None
    for node in prompt.values():
        if isinstance(node, dict) and "inputs" in node and "image" in node["inputs"]:
            image_path = node["inputs"]["image"]
            break

    jobs[prompt_id] = {"status": "processing", "outputs": {}}
    global queue_running
    queue_running = True

    asyncio.create_task(process_job(prompt_id, client_id, image_path))
    return {"prompt_id": prompt_id}


async def process_job(prompt_id: str, client_id: str, image_path: str):
    await asyncio.sleep(PROCESSING_DELAY)

    img_bytes = None
    if image_path:
        key = os.path.basename(image_path)
        img_bytes = uploaded_images.get(key)

    if not img_bytes:
        img = Image.new("RGB", (512, 512), color="white")
    else:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "dummy", fill=(255, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    out_name = f"{uuid4().hex}.png"
    uploaded_images[out_name] = data

    jobs[prompt_id] = {
        "status": "complete",
        "outputs": {
            "0": {
                "images": [
                    {"filename": out_name, "subfolder": "", "type": "output"}
                ]
            }
        },
    }

    global queue_running
    queue_running = False

    ws = websockets.get(client_id)
    if ws:
        try:
            await ws.send_json({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}})
        except Exception:
            pass


@app.get("/history/{prompt_id}")
async def get_history(prompt_id: str):
    job = jobs.get(prompt_id, {"status": "processing", "outputs": {}})
    return {prompt_id: job}


@app.get("/view")
async def view_image(filename: str, subfolder: str = "", type: str = "output"):
    data = uploaded_images.get(filename)
    if data is None:
        return Response(status_code=404)
    return Response(content=data, media_type="image/png")


@app.get("/queue")
async def queue_status():
    return {"queue_running": queue_running}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, clientId: str):
    await websocket.accept()
    websockets[clientId] = websocket
    try:
        while True:
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        websockets.pop(clientId, None)

