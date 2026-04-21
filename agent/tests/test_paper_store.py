"""Tests for uploaded paper persistence."""

import fitz

from app.config import config
from app.services import paper_store as paper_store_module


def build_pdf_bytes(title: str, body: str) -> bytes:
    document = fitz.open()
    document.set_metadata({"title": title})
    page = document.new_page()
    page.insert_text((72, 72), body)
    payload = document.tobytes()
    document.close()
    return payload


def test_save_uploaded_paper_persists_pdf_text_and_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "upload_dir", str(tmp_path))
    saved_papers = {}

    def fake_get_paper(paper_id):
        return saved_papers.get(paper_id)

    def fake_save_paper(paper):
        saved_papers[paper["paper_id"]] = dict(paper)

    monkeypatch.setattr(paper_store_module.db, "get_paper", fake_get_paper)
    monkeypatch.setattr(paper_store_module.db, "save_paper", fake_save_paper)
    pdf_bytes = build_pdf_bytes("Test Paper", "This is the body of the paper.")

    metadata = paper_store_module.save_uploaded_paper("session-1", "paper.pdf", pdf_bytes)

    assert metadata["paper_id"].startswith("paper_")
    assert metadata["title"] == "Test Paper"
    assert metadata["page_count"] == 1
    assert (tmp_path / f"{metadata['paper_id']}.pdf").exists()
    assert (tmp_path / f"{metadata['paper_id']}.txt").exists()
    assert not (tmp_path / f"{metadata['paper_id']}.json").exists()
    assert saved_papers[metadata["paper_id"]]["pdf_path"] == str(tmp_path / f"{metadata['paper_id']}.pdf")

    loaded_metadata = paper_store_module.get_paper_metadata(metadata["paper_id"])
    loaded_text = paper_store_module.get_paper_text(metadata["paper_id"])

    assert loaded_metadata["paper_id"] == metadata["paper_id"]
    assert loaded_metadata["title"] == metadata["title"]
    assert "This is the body of the paper." in loaded_text


def test_save_uploaded_paper_reuses_existing_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "upload_dir", str(tmp_path))
    saved_papers = {}

    def fake_get_paper(paper_id):
        return saved_papers.get(paper_id)

    def fake_save_paper(paper):
        saved_papers[paper["paper_id"]] = dict(paper)

    monkeypatch.setattr(paper_store_module.db, "get_paper", fake_get_paper)
    monkeypatch.setattr(paper_store_module.db, "save_paper", fake_save_paper)
    pdf_bytes = build_pdf_bytes("Duplicate Paper", "Same content every time.")

    first = paper_store_module.save_uploaded_paper("session-1", "paper.pdf", pdf_bytes)
    second = paper_store_module.save_uploaded_paper("session-2", "paper.pdf", pdf_bytes)

    assert second["paper_id"] == first["paper_id"]
    assert second["file_hash"] == first["file_hash"]
