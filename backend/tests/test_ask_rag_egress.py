"""Ask RAG 出境分轨：egress / allowed_providers / rag_local_required。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.thomas_core.config import rag_egress_for_collection


@pytest.mark.parametrize(
    "mode,collection,expected",
    [
        ("dual", "poetry_full", "cloud_ok"),
        ("dual", "looma_knowledge", "local_only"),
        ("dual", "", "local_only"),
        ("local_only", "poetry_full", "local_only"),
        ("off", "looma_knowledge", "cloud_ok"),
    ],
)
def test_rag_egress_for_collection(mode, collection, expected):
    assert (
        rag_egress_for_collection(
            collection,
            mode=mode,
            allowed=["poetry_full"],
        )
        == expected
    )


@pytest.fixture()
def core_app(tmp_path, monkeypatch):
    db = tmp_path / "looma.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("RAG_PRIVACY_MODE", "dual")
    monkeypatch.setenv("RAG_CLOUD_ALLOWED_COLLECTIONS", "poetry_full")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("CHROMA_COLLECTION", "looma_knowledge")
    from src.thomas_core.app import create_core_app

    return create_core_app()


def test_ask_local_only_restricts_to_ollama(core_app, monkeypatch):
    """dual + looma_knowledge → egress=local_only，call_llm 仅 ollama。"""
    from src.thomas_core import brain_rag

    hits = [
        {
            "id": "1",
            "content": "隐私知识片段",
            "score": 0.9,
            "metadata": {"collection": "looma_knowledge"},
        }
    ]
    captured: dict = {}

    def fake_call_llm(prompt, *, temperature=0.3, allowed_providers=None, meta=None):
        captured["allowed_providers"] = allowed_providers
        if meta is not None:
            meta["provider"] = "ollama"
            meta["model"] = "qwen2.5-coder:1.5b"
        return "本地回答"

    monkeypatch.setattr(
        "src.thomas_core.rag.chroma_client.search_chroma",
        lambda *a, **k: hits,
    )
    monkeypatch.setattr(brain_rag, "call_llm", fake_call_llm)

    # 直接测 brain_rag.dispatch（避开 consent/quota）
    with core_app.app_context():
        result = brain_rag.dispatch(intent="rag", query="测试隐私")

    assert result["egress"] == "local_only"
    assert result["rag_privacy"] == "dual"
    assert result["llm_provider"] == "ollama"
    assert captured["allowed_providers"] == ("ollama",)
    assert result["answer"] == "本地回答"


def test_ask_cloud_ok_for_poetry(core_app, monkeypatch):
    hits = [
        {
            "id": "p1",
            "content": "诗歌片段",
            "score": 0.8,
            "metadata": {"collection": "poetry_full"},
        }
    ]
    captured: dict = {}

    def fake_call_llm(prompt, *, temperature=0.3, allowed_providers=None, meta=None):
        captured["allowed_providers"] = allowed_providers
        if meta is not None:
            meta["provider"] = "deepseek"
            meta["model"] = "deepseek-chat"
        return "云端回答"

    monkeypatch.setattr(
        "src.thomas_core.rag.chroma_client.search_chroma",
        lambda *a, **k: hits,
    )
    from src.thomas_core import brain_rag

    monkeypatch.setattr(brain_rag, "call_llm", fake_call_llm)

    with core_app.app_context():
        # 强制 collection 为 poetry_full
        core_app.config["CHROMA_COLLECTION"] = "poetry_full"
        result = brain_rag.dispatch(intent="rag", query="写首诗")

    assert result["egress"] == "cloud_ok"
    assert captured.get("allowed_providers") is None
    assert result["llm_provider"] == "deepseek"


def test_ask_rag_local_required_when_ollama_down(core_app, monkeypatch):
    hits = [
        {
            "id": "1",
            "content": "私有片段",
            "score": 0.9,
            "metadata": {"collection": "looma_knowledge"},
        }
    ]

    def fake_call_llm(prompt, *, temperature=0.3, allowed_providers=None, meta=None):
        if meta is not None:
            meta["provider"] = None
        return None

    monkeypatch.setattr(
        "src.thomas_core.rag.chroma_client.search_chroma",
        lambda *a, **k: hits,
    )
    from src.thomas_core import brain_rag

    monkeypatch.setattr(brain_rag, "call_llm", fake_call_llm)

    with core_app.app_context():
        result = brain_rag.dispatch(intent="rag", query="隐私问")

    assert result["egress"] == "local_only"
    assert result["error"] == "rag_local_required"
    assert "本地模型" in result["answer"]


def test_deepseek_rag_answer_disabled():
    from src.thomas_core.llm.deepseek_client import rag_answer

    with pytest.raises(RuntimeError, match="disabled"):
        rag_answer("q", ["chunk"])


def test_ask_route_exposes_egress(core_app, monkeypatch):
    """POST /ask 响应含 egress / rag_privacy / llm_provider。"""
    from src.thomas_core.compliance import consent as consent_mod

    class _AlwaysOk:
        def check(self, uid, scope):
            return True

    monkeypatch.setattr(consent_mod, "get_consent_manager", lambda: _AlwaysOk())
    monkeypatch.setattr(
        "src.thomas_core.routes.ask_routes.consume_with_boost",
        lambda *a, **k: {"ok": True, "source": "daily"},
    )

    def fake_parse(query, navigator_mode=False):
        return "rag", 0.9, {}

    def fake_dispatch(**kwargs):
        return {
            "answer": "ok",
            "egress": "local_only",
            "rag_privacy": "dual",
            "llm_provider": "ollama",
            "_sources": [],
        }

    monkeypatch.setattr(
        "src.thomas_core.brain.get_brain",
        lambda: (fake_parse, fake_dispatch),
    )

    resp = core_app.test_client().post("/v1/ask", json={"query": "hello egress"})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["egress"] == "local_only"
    assert data["rag_privacy"] == "dual"
    assert data["llm_provider"] == "ollama"
    assert data["answer"] == "ok"