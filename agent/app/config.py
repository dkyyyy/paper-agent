"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # gRPC
    grpc_port: int = int(os.getenv("GRPC_PORT", "50051"))

    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "dashscope")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")

    # Embedding
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Chroma
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))

    # Upload
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")


config = Config()
