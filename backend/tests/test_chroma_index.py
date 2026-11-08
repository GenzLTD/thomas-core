"""画像向量不得在请求线程里下载 ONNX。"""
from __future__ import annotations

import socket
import time

from src.thomas_core.profile import chroma_index


def test_missing_onnx_cache_uses_deterministic_embeddings(tmp_path, monkeypatch):
    monkeypatch.setattr(chroma_index, "_onnx_dir", lambda: tmp_path / "missing-onnx")
    monkeypatch.setenv("PROFILE_EMBED", "onnx")
    socket.setdefaulttimeout(2)

    started = time.perf_counter()
    ok = chroma_index.upsert_event(
        str(tmp_path / "core.db"),
        "event-1",
        "quiz result",
        {"user_id": "user-1", "domain": "learning", "consent_scope": "game_quiz"},
    )

    assert ok is True
    assert time.perf_counter() - started < 5
    found = chroma_index.vectors_for_user(str(tmp_path / "core.db"), "user-1")
    assert [row["id"] for row in found] == ["event-1"]
