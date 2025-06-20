from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import structlog
import logging
# from sentry_sdk import init as sentry_init
# from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from core.config import settings
from utils.log_sender import LogSender
from utils.worker import Worker

from routes.routes import router as rest_router

import os
import asyncio


BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "frontend/static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "frontend/templates")

logging.basicConfig(level=logging.INFO, format="%(message)s")

# sentry_init(
#     dsn=settings.SENTRY_DSN,
#     traces_sample_rate=1.0,
# )

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
log = structlog.get_logger(__name__)

log_sender = LogSender(
    log_api=settings.LOG_API,
    project_id=settings.LOG_PROJECT_ID,
    upload_delay=120
)

app = FastAPI()
# app.add_middleware(SentryAsgiMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar conforme política de produção
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(rest_router)

server_list = [settings.COMFYUI_API_SERVER, settings.COMFYUI_API_SERVER2,
               settings.COMFYUI_API_SERVER3, settings.COMFYUI_API_SERVER4]

worker = Worker(server_list)

@app.on_event("startup")
async def start_worker():
    """
    Inicia o worker_loop em paralelo ao servidor.
    """
    log.info("worker.startup")
    asyncio.create_task(worker.worker_loop())