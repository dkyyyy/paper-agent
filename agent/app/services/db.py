"""PostgreSQL persistence helpers."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import Any
from uuid import UUID

from app.config import config

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:  # pragma: no cover - exercised via runtime environment.
    psycopg2 = None
    Json = None
    RealDictCursor = None
    ThreadedConnectionPool = None


logger = logging.getLogger(__name__)
_connection_pool = None


def get_connection_pool():
    """Create or reuse the shared PostgreSQL connection pool."""
    global _connection_pool

    if psycopg2 is None or ThreadedConnectionPool is None:
        raise RuntimeError("psycopg2 is required for PostgreSQL persistence")
    if _connection_pool is None:
        _connection_pool = ThreadedConnectionPool(
            minconn=config.postgres_pool_min_connections,
            maxconn=config.postgres_pool_max_connections,
            host=config.postgres_host,
            port=config.postgres_port,
            user=config.postgres_user,
            password=config.postgres_password,
            dbname=config.postgres_dbname,
            sslmode=config.postgres_sslmode,
        )
    return _connection_pool


@contextmanager
def connection():
    """Borrow a connection from the shared PostgreSQL pool."""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def _json(value: dict[str, Any] | None) -> Any:
    payload = value or {}
    if Json is None:
        return payload
    return Json(payload)


def _normalize_session_id(session_id: str) -> str:
    try:
        return str(UUID(session_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("session_id must be a valid UUID") from exc


def _normalize_paper(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None

    paper = dict(row)
    paper["paper_id"] = paper.pop("id")
    paper["authors"] = paper.get("authors") or []
    paper["extracted_info"] = paper.get("extracted_info") or {}
    return paper


def save_paper(paper: dict[str, Any]) -> None:
    """Insert or update a paper metadata row."""
    paper_id = paper.get("paper_id") or paper.get("id")
    if not paper_id:
        raise ValueError("paper_id is required")

    with connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO papers (
                        id, title, authors, abstract, year, source, doi, url,
                        citation_count, extracted_info, pdf_path, is_indexed, file_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        authors = EXCLUDED.authors,
                        abstract = EXCLUDED.abstract,
                        year = EXCLUDED.year,
                        source = EXCLUDED.source,
                        doi = EXCLUDED.doi,
                        url = EXCLUDED.url,
                        citation_count = EXCLUDED.citation_count,
                        extracted_info = EXCLUDED.extracted_info,
                        pdf_path = EXCLUDED.pdf_path,
                        is_indexed = EXCLUDED.is_indexed,
                        file_hash = EXCLUDED.file_hash,
                        updated_at = NOW()
                    """,
                    (
                        paper_id,
                        paper.get("title", ""),
                        paper.get("authors") or [],
                        paper.get("abstract"),
                        paper.get("year"),
                        paper.get("source", "upload"),
                        paper.get("doi"),
                        paper.get("url"),
                        paper.get("citation_count", 0),
                        _json(paper.get("extracted_info")),
                        paper.get("pdf_path"),
                        paper.get("is_indexed", False),
                        paper.get("file_hash"),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_paper(paper_id: str) -> dict[str, Any] | None:
    """Load paper metadata by primary key."""
    with connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id, title, authors, abstract, year, source, doi, url,
                    citation_count, extracted_info, pdf_path, is_indexed,
                    file_hash, created_at, updated_at
                FROM papers
                WHERE id = %s
                """,
                (paper_id,),
            )
            return _normalize_paper(cur.fetchone())


def save_message(session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    """Persist a session row and append a message."""
    if not session_id:
        raise ValueError("session_id is required")
    if not role:
        raise ValueError("role is required")
    if not content:
        raise ValueError("content is required")

    session_id = _normalize_session_id(session_id)
    title = None
    if role == "user":
        title = content[:50] + ("..." if len(content) > 50 else "")

    with connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (id, title, created_at, updated_at)
                    VALUES (%s, %s, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        title = COALESCE(sessions.title, EXCLUDED.title),
                        updated_at = NOW()
                    """,
                    (session_id, title),
                )
                cur.execute(
                    """
                    INSERT INTO messages (session_id, role, content, metadata, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    """,
                    (session_id, role, content, _json(metadata)),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def list_sessions() -> list[dict[str, Any]]:
    """Return session summaries ordered by recent activity."""
    with connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    COALESCE(latest.content, '') AS last_message,
                    COALESCE(message_counts.message_count, 0) AS message_count
                FROM sessions AS s
                LEFT JOIN (
                    SELECT session_id, COUNT(*)::BIGINT AS message_count
                    FROM messages
                    GROUP BY session_id
                ) AS message_counts
                    ON message_counts.session_id = s.id
                LEFT JOIN LATERAL (
                    SELECT content
                    FROM messages
                    WHERE session_id = s.id
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                ) AS latest ON TRUE
                ORDER BY s.updated_at DESC, s.created_at DESC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "session_id": row["id"],
            "title": row.get("title") or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_message": row.get("last_message") or "",
            "message_count": int(row.get("message_count") or 0),
        }
        for row in rows
    ]
