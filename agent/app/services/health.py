"""Runtime dependency probes used by HealthCheck and diagnostics."""

from app.rag.embeddings import get_embeddings
from app.rag.indexer import get_chroma_client
from app.services.cache import search_cache


def probe_services() -> tuple[bool, dict[str, str]]:
    services: dict[str, str] = {}

    try:
        from app.agents.llm import get_llm

        get_llm()
        services["llm"] = "ok"
    except Exception as exc:
        services["llm"] = f"error: {exc}"

    try:
        get_embeddings()
        services["embeddings"] = "ok"
    except Exception as exc:
        services["embeddings"] = f"error: {exc}"

    try:
        search_cache.client.ping()
        services["redis"] = "ok"
    except Exception as exc:
        services["redis"] = f"error: {exc}"

    try:
        get_chroma_client().heartbeat()
        services["chroma"] = "ok"
    except Exception as exc:
        services["chroma"] = f"error: {exc}"

    try:
        from app.config import config

        config.ensure_upload_dir()
        services["upload"] = "ok"
    except Exception as exc:
        services["upload"] = f"error: {exc}"

    healthy = all(status == "ok" for status in services.values())
    return healthy, services