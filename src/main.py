from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi_socketio import SocketManager

import structlog
from sentry_sdk import init as sentry_init
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from core.config import settings
from core.udp_sender import UDPSender
from core.comfyui_api  import ComfyUiAPI
from utils.log_sender import LogSender

from routes.routes import router as rest_router
from routes.sockets import register_socket_handlers

import os
import threading
import shutil
import time

# ----------------------------
# Inicializações gerais
# ----------------------------

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "frontend/static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "frontend/templates")

sentry_init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=1.0,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()

log_sender = LogSender(
    log_api=settings.LOG_API,
    project_id=settings.LOG_PROJECT_ID,
    upload_delay=120
)

app = FastAPI()
app.add_middleware(SentryAsgiMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar conforme política de produção
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

socket_manager = SocketManager(app=app, async_mode="asgi")
app.state.socket_manager = socket_manager

udp_sender = UDPSender(port=settings.UDP_PORT)
ss_api = ComfyUiAPI(
    settings.COMFYUI_API_SERVER,
    settings.IMAGE_TEMP_FOLDER,
    settings.WORKFLOW_PATH,
    settings.WORKFLOW_NODE_ID_KSAMPLER,
    settings.WORKFLOW_NODE_ID_IMAGE_LOAD,
    settings.WORKFLOW_NODE_ID_TEXT_INPUT
)

app.include_router(rest_router)

register_socket_handlers(socket_manager)

# ---------------------------------------------
# Função periódica para remover pastas antigas
# ---------------------------------------------
def remove_old_folders():
    """
    A cada execução, verifica em static/download_images subpastas criadas e remove
    aquelas com mais de 10 minutos.
    """
    while True:
        current_time = time.time()
        directory = os.path.join(STATIC_DIR, "download_images")
        minutes = 10

        for foldername in os.listdir(directory):
            folder_path = os.path.join(directory, foldername)
            if os.path.isdir(folder_path):
                creation_time = os.path.getctime(folder_path)
                if (current_time - creation_time) / 60 > minutes:
                    shutil.rmtree(folder_path)
                    log.info(f'Pasta removida por tempo excedido', folder=foldername)
        time.sleep(60)

# Inicia em background a limpeza periódica
threading.Thread(target=remove_old_folders, daemon=True).start()

@app.get("/")
async def root():
    return RedirectResponse(url="/cta")

@app.get("/alive")
async def alive():
    return "Alive"
