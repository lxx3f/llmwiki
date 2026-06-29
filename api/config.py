import uuid
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_user_id() -> str:
    return str(uuid.uuid4())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    # Database
    DATABASE_URL: str

    # Single user
    SINGLE_USER_ID: str = _default_user_id()

    # Local storage
    STORAGE_ROOT: str = "./data/files/"

    # Ollama (embedding + local LLM)
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    LLM_MODEL: str = "qwen2.5:7b"  # for knowledge extraction, Q&A etc.
    EMBEDDING_DIM: int = 768

    # OCR / document processing
    MISTRAL_API_KEY: str = ""
    PDF_BACKEND: str = "pdf_oxide"  # "pdf_oxide" or "mistral"

    # Converter service
    CONVERTER_URL: str = ""
    CONVERTER_SECRET: str = ""

    # Observability
    LOGFIRE_TOKEN: str = ""
    SENTRY_DSN: str = ""

    # URLs
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    MCP_URL: str = "http://localhost:8080/mcp"

    # Quotas (retained for optional caps, set high for single user)
    QUOTA_MAX_PAGES_PER_DOC: int = 300
    GLOBAL_OCR_ENABLED: bool = True
    GLOBAL_MAX_PAGES: int = 50000


settings = Settings()
