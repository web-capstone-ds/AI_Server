from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # FastAPI
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_ENV: Literal["development", "production", "test"] = "production"

    # Authentication
    AI_INGEST_API_KEY: str
    BACKEND_JWT_SECRET: str
    BACKEND_SERVER_URL: str = "http://web-backend:8080"

    # PostgreSQL + pgvector
    PG_HOST: str = "localhost"
    PG_PORT: int = 5432
    PG_NAME: str = "ai_server"
    PG_USER: str = "ai_server"
    PG_PASSWORD: str
    PG_POOL_MIN: int = 2
    PG_POOL_MAX: int = 10

    # Anthropic API
    ANTHROPIC_API_KEY: str
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20240620"
    ANTHROPIC_MAX_TOKENS: int = 4096

    # Embedding Model
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = 16
    EMBEDDING_MAX_SEQ_LENGTH: int = 512
    EMBEDDING_USE_ONNX: bool = True

    # Scheduler
    DAILY_REPORT_CRON: str = "0 0 * * *"
    WEEKLY_REPORT_CRON: str = "0 0 * * 1"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.PG_USER}:{self.PG_PASSWORD}@{self.PG_HOST}:{self.PG_PORT}/{self.PG_NAME}"

settings = Settings()
