"""Central configuration, loaded from environment / .env.

LLM_BASE_URL and EMBED_BASE_URL select local or hosted compatible endpoints;
the rest of the application does not need provider-specific branches.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class Settings:
    # Chat model
    llm_base_url: str = _get("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_api_key: str = _get("LLM_API_KEY", "ollama")
    llm_model: str = _get("LLM_MODEL", "qwen2.5")

    # Embedding model
    embed_base_url: str = _get("EMBED_BASE_URL", "http://localhost:11434/v1")
    embed_api_key: str = _get("EMBED_API_KEY", "ollama")
    embed_model: str = _get("EMBED_MODEL", "nomic-embed-text")

    # Retrieval / chunking
    top_k: int = int(_get("TOP_K", "5"))
    # Optional LLM rerank of retrieval candidates. Improves definitional
    # questions at the cost of one extra LLM call per question.
    rerank: bool = _get("RERANK", "0").lower() in ("1", "true", "yes")
    chunk_size: int = int(_get("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(_get("CHUNK_OVERLAP", "150"))

    # Storage
    data_dir: Path = Path(_get("DATA_DIR", "data"))

    # Optional shared password for the UI/API. Empty = auth disabled (default,
    # fine for localhost). Set it if the app is exposed beyond the machine.
    app_password: str = _get("APP_PASSWORD", "")
    cookie_secure: bool = _get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")

    @property
    def index_path(self) -> Path:
        return self.data_dir / "faiss.index"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "store.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
