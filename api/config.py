import uuid
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_user_id() -> str:
    return "local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    # File-system storage (replaces PostgreSQL)
    WIKI_ROOT: str = "./wiki_data/"

    # Single user
    SINGLE_USER_ID: str = _default_user_id()

    # Local storage (deprecated — kept for TUS upload temp files)
    STORAGE_ROOT: str = "./data/files/"

    # Ollama (embedding + local LLM)
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    LLM_MODEL: str = "qwen2.5:14b"  # for knowledge extraction, Q&A etc.
    EMBEDDING_DIM: int = 768

    # OCR / document processing
    MISTRAL_API_KEY: str = ""
    PDF_BACKEND: str = "pdf_oxide"  # "pdf_oxide" or "mistral"

    # Observability
    LOGFIRE_TOKEN: str = ""
    SENTRY_DSN: str = ""

    # URLs
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:8021"
    API_URL: str = "http://localhost:8021"

    # Quotas (retained for optional caps, set high for single user)
    QUOTA_MAX_PAGES_PER_DOC: int = 300
    GLOBAL_OCR_ENABLED: bool = True
    GLOBAL_MAX_PAGES: int = 50000


settings = Settings()
