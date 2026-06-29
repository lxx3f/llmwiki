from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    DATABASE_URL: str
    SINGLE_USER_ID: str = ""
    STORAGE_ROOT: str = "./data/files/"
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIM: int = 768
    LOGFIRE_TOKEN: str = ""
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:8000"
    MCP_URL: str = "http://localhost:8080/mcp"
    SENTRY_DSN: str = ""


settings = Settings()
