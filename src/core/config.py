from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    BASE_URL: str = Field(..., env="BASE_URL")
    DIRECTORY: str = Field("data", env="DIRECTORY")
    UDP_PORT: int = Field(default=7001, env="UDP_PORT")
    TIMER_TERMS: str = Field(20, env="TIMER_TERMS")
    COMFYUI_API_SERVER: str = Field(default=None, env="COMFYUI_API_SERVER")
    IMAGE_TEMP_FOLDER: str = Field(default="static/outputs", env="IMAGE_TEMP_FOLDER")
    REDIS_URL: str = Field(..., env="REDIS_URL")
    SENTRY_DSN: Optional[str] = Field(default=None, env="SENTRY_DSN")
    WORKFLOW_PATH: str = Field(default="workflows/comfyui_basic.json", env="WORKFLOW_PATH")
    WORKFLOW_NODE_ID_KSAMPLER: str = Field(default="3", env="WORKFLOW_NODE_ID_KSAMPLER")
    WORKFLOW_NODE_ID_IMAGE_LOAD: str = Field(default="15", env="WORKFLOW_NODE_ID_IMAGE_LOAD")
    WORKFLOW_NODE_ID_TEXT_INPUT: str = Field(default="18", env="WORKFLOW_NODE_ID_TEXT_INPUT")
    CONFIG_INDEX: str = Field(default=6, env="CONFIG_INDEX")
    LOG_API: Optional[str] = Field(default=None, env="LOG_API")
    LOG_PROJECT_ID: Optional[str] = Field(default=None, env="LOG_PROJECT_ID")
    SMS_API_URL: Optional[str] = Field(default=None, env='SMS_API_URL')
    SMS_API_KEY: Optional[str] = Field(default=None, env='SMS_API_KEY')
    DEFAULT_PROCESSING_TIME: int = Field(8000, env="DEFAULT_PROCESSING_TIME")


    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()