"""RAG 分轨 health 字段：ollama_ok / rag_privacy_mode（106 V10 / orch smoke）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def core_app(tmp_path, monkeypatch):
    db = tmp_path / "looma.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("RAG_PRIVACY_MODE", "dual")
    monkeypatch.setenv("RAG_CLOUD_ALLOWED_COLLECTIONS", "poetry_full")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    from src.thomas_core.app import create_core_app

    return create_core_app()


def test_health_exposes_rag_privacy_fields_when_ollama_up(core_app, monkeypatch):
    resp_mock = MagicMock()
    resp_mock.status_code = 200

    import requests as req_mod

    monkeypatch.setattr(req_mod, "get", lambda *a, **k: resp_mock)

    data = core_app.test_client().get("/health").get_json()
    assert data["service"] == "thomas-core"
    assert data["ollama_ok"] is True
    assert data["ollama_status"] == "ok"
    assert data["rag_privacy_mode"] == "dual"
    assert data["rag_cloud_allowed_collections"] == ["poetry_full"]


def test_health_ollama_unreachable(core_app, monkeypatch):
    import requests as req_mod

    def _boom(*a, **k):
        raise req_mod.ConnectionError("down")

    monkeypatch.setattr(req_mod, "get", _boom)
    data = core_app.test_client().get("/health").get_json()
    assert data["ollama_ok"] is False
    assert data["ollama_status"] == "unreachable"
    assert data["rag_privacy_mode"] == "dual"
