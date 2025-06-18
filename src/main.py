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
from utils.worker import worker_loop

from routes.routes import router as rest_router

import os
import asyncio


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

app.include_router(rest_router)

@app.on_event("startup")
async def start_worker():
    """
    Inicia o worker_loop em paralelo ao servidor.
    """
    log.info("worker.startup")
    asyncio.create_task(worker_loop())