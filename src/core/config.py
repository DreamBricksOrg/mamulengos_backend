from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    MONGO_URI: str = Field(..., env="MONGO_URI")
    MONGO_DB: str = Field("intel", env="MONGO_DB")
    JWT_SECRET: str = Field(..., env="JWT_SECRET")
    JWT_ALGORITHM: str = Field("HS256", env="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    ADMIN_CREATION_TOKEN: str = Field(..., env="ADMIN_CREATION_TOKEN")
    RATE_LIMIT_PER_DAY: int = Field(5, env="RATE_LIMIT_PER_DAY")
    REDIS_URL: str = Field(..., env="REDIS_URL")
    SENTRY_DSN: str = Field(..., env="SENTRY_DSN")
    AWS_ACCESS_KEY_ID: str = Field(..., env="AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str = Field(..., env="AWS_SECRET_ACCESS_KEY") 
    AWS_REGION: str = Field(..., env="AWS_REGION")
    S3_BUCKET: str = Field(..., env="S3_BUCKET")
    LOG_API: str = Field(..., env="LOG_API")
    LOG_ID: str = Field(..., env="LOG_ID")

    class Config:
        env_file = ".env"

settings = Settings()