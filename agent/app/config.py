"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_str(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_int(*names: str, default: int) -> int:
    return int(_env_str(*names, default=str(default)))


def _env_float(*names: str, default: float) -> float:
    return float(_env_str(*names, default=str(default)))


@dataclass
class Config:
    # gRPC
    grpc_port: int = _env_int("GRPC_PORT", default=50051)

    # Chat LLM
    llm_provider: str = _env_str("LLM_PROVIDER", default="dashscope").lower()
    llm_api_key: str = _env_str(
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "ZHIPUAI_API_KEY",
    )
    llm_model: str = _env_str("LLM_MODEL", "MODEL_NAME", "OPENAI_MODEL", default="qwen-plus")
    llm_base_url: str = _env_str("LLM_BASE_URL", "OPENAI_API_BASE", "DEEPSEEK_BASE_URL")

    # Embeddings
    embedding_provider: str = _env_str("EMBEDDING_PROVIDER").lower()
    embedding_api_key: str = _env_str(
        "EMBEDDING_API_KEY",
        "EMBEDDING_OPENAI_API_KEY",
        "EMBEDDING_DASHSCOPE_API_KEY",
    )
    embedding_model: str = _env_str("EMBEDDING_MODEL", "TEXT_EMBEDDING_MODEL")
    embedding_base_url: str = _env_str("EMBEDDING_BASE_URL")
    local_embedding_dimensions: int = _env_int("LOCAL_EMBEDDING_DIMENSIONS", default=768)

    # Redis
    redis_url: str = _env_str("REDIS_URL", default="redis://localhost:6379/0")
    search_cache_ttl_seconds: int = _env_int("SEARCH_CACHE_TTL_SECONDS", default=3600)

    # PostgreSQL
    postgres_host: str = _env_str("POSTGRES_HOST", default="localhost")
    postgres_port: int = _env_int("POSTGRES_PORT", default=5432)
    postgres_user: str = _env_str("POSTGRES_USER", default="paper_agent")
    postgres_password: str = _env_str("POSTGRES_PASSWORD", default="paper_agent")
    postgres_dbname: str = _env_str("POSTGRES_DBNAME", "POSTGRES_DB", default="paper_agent")
    postgres_sslmode: str = _env_str("POSTGRES_SSLMODE", default="disable")
    postgres_pool_min_connections: int = _env_int("POSTGRES_POOL_MIN_CONNECTIONS", default=1)
    postgres_pool_max_connections: int = _env_int("POSTGRES_POOL_MAX_CONNECTIONS", default=4)

    # Chroma
    chroma_host: str = _env_str("CHROMA_HOST", default="localhost")
    chroma_port: int = _env_int("CHROMA_PORT", default=8000)

    # Upload / pipeline
    upload_dir: str = _env_str("UPLOAD_DIR", default="./uploads")
    max_analysis_papers: int = _env_int("MAX_ANALYSIS_PAPERS", default=5)

    # Token budget
    session_token_budget: int = _env_int("SESSION_TOKEN_BUDGET", default=50000)
    token_compress_threshold: float = _env_float("TOKEN_COMPRESS_THRESHOLD", default=0.8)
    token_reserved_output_tokens: int = _env_int("TOKEN_RESERVED_OUTPUT_TOKENS", default=2000)
    token_keep_recent_turns: int = _env_int("TOKEN_KEEP_RECENT_TURNS", default=3)

    # Network proxy
    http_proxy: str = _env_str("HTTP_PROXY", "http_proxy")
    https_proxy: str = _env_str("HTTPS_PROXY", "https_proxy")

    # Academic API keys
    semantic_scholar_api_key: str = _env_str("SEMANTIC_SCHOLAR_API_KEY")

    @property
    def effective_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        if self.llm_provider == "deepseek":
            return "https://api.deepseek.com"
        if self.llm_provider == "openai":
            return "https://api.openai.com/v1"
        return ""

    @property
    def effective_embedding_provider(self) -> str:
        if self.embedding_provider:
            return self.embedding_provider
        if self.llm_provider == "dashscope":
            return "dashscope"
        if self.llm_provider == "openai" and "deepseek.com" not in self.effective_llm_base_url.lower():
            return "openai"
        if self.embedding_api_key:
            return "openai"
        return "local"

    @property
    def effective_embedding_api_key(self) -> str:
        if self.embedding_api_key:
            return self.embedding_api_key
        if self.effective_embedding_provider == self.llm_provider:
            return self.llm_api_key
        if self.effective_embedding_provider == "dashscope":
            return _env_str("DASHSCOPE_API_KEY")
        if self.effective_embedding_provider == "openai":
            return _env_str("OPENAI_API_KEY")
        return ""

    @property
    def effective_embedding_model(self) -> str:
        if self.embedding_model:
            return self.embedding_model
        if self.effective_embedding_provider == "dashscope":
            return "text-embedding-v3"
        if self.effective_embedding_provider == "openai":
            return "text-embedding-3-small"
        if self.effective_embedding_provider in {"huggingface", "bge"}:
            return "BAAI/bge-small-zh-v1.5"
        return f"local-hash-{self.local_embedding_dimensions}"

    @property
    def effective_embedding_base_url(self) -> str:
        if self.embedding_base_url:
            return self.embedding_base_url.rstrip("/")
        if self.effective_embedding_provider == "openai":
            if self.llm_provider == "openai" and self.effective_embedding_provider == self.llm_provider:
                return self.effective_llm_base_url
            return "https://api.openai.com/v1"
        return ""

    @property
    def resolved_upload_dir(self) -> Path:
        return Path(self.upload_dir).expanduser().resolve()

    def ensure_upload_dir(self) -> Path:
        path = self.resolved_upload_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


config = Config()
