"""profile_context 检索层。不可用时调用方继续走 SQL，不拖垮核。"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger("looma.profile.chroma")

COLLECTION = "profile_context"
_REQUIRED = ("user_id", "domain", "consent_scope")
_clients: dict[str, object] = {}


class DeterministicEmbedding:
    """测试用嵌入。不下载模型，只为 smoke 验证 metadata 往返。"""

    def name(self) -> str:
        return "deterministic"

    def __call__(self, input):
        return [self._vec(text) for text in input]

    @staticmethod
    def _vec(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255.0 for byte in digest[:32]]


def chroma_dir(db_path: str) -> Path:
    """与库文件同目录的 chroma/。DATABASE_PATH 为绝对路径时，不落进 releases。"""
    database = Path(db_path)
    if not database.is_absolute():
        database = database.resolve()
    return database.parent / "chroma"


def chroma_ready(db_path: str) -> bool:
    """只探测客户端能否打开。不加载 ONNX，不把检索层故障变成核故障。"""
    try:
        _client(chroma_dir(db_path))
        return True
    except Exception:
        logger.info("chroma unavailable", exc_info=True)
        return False


def _client(path: Path):
    key = str(path)
    cached = _clients.get(key)
    if cached is not None:
        return cached
    import chromadb
    from chromadb.config import Settings

    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=key,
        settings=Settings(anonymized_telemetry=False),
    )
    _clients[key] = client
    return client


def _embedding():
    mode = os.getenv("PROFILE_EMBED", "onnx").strip().lower() or "onnx"
    if mode == "deterministic":
        return DeterministicEmbedding()
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


def _collection(db_path: str):
    client = _client(chroma_dir(db_path))
    return client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=_embedding(),
        metadata={"hnsw:space": "cosine"},
    )


def _require_metadata(metadata: dict) -> None:
    missing = [key for key in _REQUIRED if not str(metadata.get(key) or "").strip()]
    if missing:
        raise ValueError("chroma metadata missing: " + ",".join(missing))


def upsert_event(db_path: str, event_id: str, document: str, metadata: dict) -> bool:
    _require_metadata(metadata)
    try:
        _collection(db_path).upsert(
            ids=[event_id],
            documents=[document],
            metadatas=[metadata],
        )
        return True
    except Exception:
        logger.warning("profile chroma upsert skipped for %s", event_id, exc_info=True)
        return False


def vectors_for_user(db_path: str, user_id: str, domains: list[str] | None = None) -> list[dict]:
    where: dict = {"user_id": user_id}
    if domains:
        where = {"$and": [{"user_id": user_id}, {"domain": {"$in": domains}}]}
    try:
        found = _collection(db_path).get(where=where, include=["documents", "metadatas"])
    except Exception:
        logger.warning("profile chroma get skipped for %s", user_id, exc_info=True)
        return []
    ids = found.get("ids") or []
    docs = found.get("documents") or []
    metas = found.get("metadatas") or []
    return [
        {"id": ids[i], "document": docs[i] if i < len(docs) else "", "metadata": metas[i] if i < len(metas) else {}}
        for i in range(len(ids))
    ]


def delete_user(db_path: str, user_id: str) -> int:
    try:
        coll = _collection(db_path)
        found = coll.get(where={"user_id": user_id})
        count = len(found.get("ids") or [])
        if count:
            coll.delete(where={"user_id": user_id})
        return count
    except Exception:
        logger.warning("profile chroma delete skipped for %s", user_id, exc_info=True)
        return -1
