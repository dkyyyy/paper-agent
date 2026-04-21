"""Tests for PostgreSQL persistence helpers."""

from __future__ import annotations

import importlib
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest


class FakeCursor:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=None, row=None):
        self.cursor_obj = FakeCursor(rows=rows, row=row)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeThreadedConnectionPool:
    def __init__(self, minconn, maxconn, **kwargs):
        self.minconn = minconn
        self.maxconn = maxconn
        self.kwargs = kwargs
        self.connections = []
        self.returned = []

    def getconn(self):
        conn = FakeConnection()
        self.connections.append(conn)
        return conn

    def putconn(self, conn):
        self.returned.append(conn)

    def closeall(self):
        return None


def fake_connection_context(conn):
    @contextmanager
    def _manager():
        yield conn

    return _manager()


def load_db_module(monkeypatch, pool_cls=FakeThreadedConnectionPool):
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = lambda *args, **kwargs: None
    fake_psycopg2.extras = types.SimpleNamespace(RealDictCursor=object, Json=lambda value: value)
    fake_psycopg2.pool = types.SimpleNamespace(ThreadedConnectionPool=pool_cls)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_psycopg2.extras)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", fake_psycopg2.pool)

    import app.services.db as db_module

    return importlib.reload(db_module)


def test_save_paper_upserts_metadata(monkeypatch):
    db = load_db_module(monkeypatch)
    conn = FakeConnection()
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    db.save_paper(
        {
            "paper_id": "paper_abc",
            "title": "A Test Paper",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "abstract": "Testing persistence.",
            "year": 2026,
            "source": "upload",
            "doi": "",
            "url": "",
            "citation_count": 0,
            "extracted_info": {"page_count": 3},
            "pdf_path": "/tmp/paper_abc.pdf",
            "is_indexed": False,
            "file_hash": "abc123",
        }
    )

    assert conn.committed is True
    assert len(conn.cursor_obj.executed) == 1
    query, params = conn.cursor_obj.executed[0]
    assert "INSERT INTO papers" in query
    assert params[0] == "paper_abc"
    assert params[1] == "A Test Paper"
    assert params[2] == ["Ada Lovelace", "Grace Hopper"]
    assert params[-1] == "abc123"


def test_connection_pool_is_initialized_once(monkeypatch):
    created_pools = []

    class TrackingPool(FakeThreadedConnectionPool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_pools.append(self)

    db = load_db_module(monkeypatch, pool_cls=TrackingPool)

    first = db.get_connection_pool()
    second = db.get_connection_pool()

    assert first is second
    assert len(created_pools) == 1


def test_get_paper_returns_none_when_missing(monkeypatch):
    db = load_db_module(monkeypatch)
    conn = FakeConnection(row=None)
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    assert db.get_paper("missing-paper") is None


def test_get_paper_maps_id_to_paper_id(monkeypatch):
    db = load_db_module(monkeypatch)
    conn = FakeConnection(
        row={
            "id": "paper_abc",
            "title": "A Test Paper",
            "authors": ["Ada Lovelace"],
            "abstract": "Testing persistence.",
            "year": 2026,
            "source": "upload",
            "doi": "",
            "url": "",
            "citation_count": 0,
            "extracted_info": {"page_count": 3},
            "pdf_path": "/tmp/paper_abc.pdf",
            "is_indexed": False,
            "file_hash": "abc123",
            "created_at": datetime(2026, 4, 20, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 20, tzinfo=timezone.utc),
        }
    )
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    paper = db.get_paper("paper_abc")

    assert paper["paper_id"] == "paper_abc"
    assert paper["title"] == "A Test Paper"
    assert paper["authors"] == ["Ada Lovelace"]
    assert paper["extracted_info"] == {"page_count": 3}


def test_save_message_creates_session_and_message(monkeypatch):
    db = load_db_module(monkeypatch)
    conn = FakeConnection()
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    db.save_message(
        session_id="9d0b39f5-ccfb-41a4-badc-d740f0a3154e",
        role="user",
        content="Explain RAG optimization trends",
        metadata={"attachment_ids": ["paper_1"]},
    )

    assert conn.committed is True
    assert len(conn.cursor_obj.executed) == 2
    assert "INSERT INTO sessions" in conn.cursor_obj.executed[0][0]
    assert "INSERT INTO messages" in conn.cursor_obj.executed[1][0]


def test_save_message_rejects_invalid_uuid_before_query(monkeypatch):
    db = load_db_module(monkeypatch)
    conn = FakeConnection()
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    with pytest.raises(ValueError, match="valid UUID"):
        db.save_message(
            session_id="session-1",
            role="user",
            content="Explain RAG optimization trends",
            metadata={"attachment_ids": ["paper_1"]},
        )

    assert conn.cursor_obj.executed == []


def test_list_sessions_returns_session_summaries(monkeypatch):
    db = load_db_module(monkeypatch)
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    conn = FakeConnection(
        rows=[
            {
                "id": "session-1",
                "title": "RAG survey",
                "created_at": now,
                "updated_at": now,
                "last_message": "Latest assistant response",
                "message_count": 2,
            }
        ]
    )
    monkeypatch.setattr(db, "connection", lambda: fake_connection_context(conn))

    sessions = db.list_sessions()

    assert sessions == [
        {
            "session_id": "session-1",
            "title": "RAG survey",
            "created_at": now,
            "updated_at": now,
            "last_message": "Latest assistant response",
            "message_count": 2,
        }
    ]
