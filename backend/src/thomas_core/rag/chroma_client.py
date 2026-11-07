"""
ChromaDB Client — Vector search for RAG knowledge base.
Migrated from old chroma_client/vector_store, adapted for Flask.
Supports local (embedded) and remote (Docker container) modes.
"""
from __future__ import annotations
from __future__ import annotations
import logging
from flask import current_app

logger = logging.getLogger("looma.chroma")

_chroma_client = None


def _get_client():
    """Get or initialize ChromaDB client."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    config = current_app.config
    mode = config.get("CHROMA_MODE", "local")

    try:
        import chromadb
        if mode == "remote":
            host = config.get("CHROMA_HOST", "localhost")
            port = int(config.get("CHROMA_PORT", 8000))
            _chroma_client = chromadb.HttpClient(host=host, port=port)
            logger.info(f"ChromaDB: remote mode (host={host}, port={port})")
        else:
            from pathlib import Path
            db_dir = Path(config.get("DATABASE_PATH", "data/looma.db")).parent / "chroma"
            db_dir.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(db_dir))
            logger.info(f"ChromaDB: local persistent mode (path={db_dir})")
    except ImportError:
        logger.warning("chromadb not installed — RAG search unavailable")
        return None
    except Exception as e:
        logger.error(f"ChromaDB init failed: {e}")
        return None

    return _chroma_client


def search_chroma(query: str, n_results: int = 5, collection: str | None = None) -> list[dict]:
    """Search ChromaDB for relevant chunks.

    Args:
        query: search query text
        n_results: number of results to return
        collection: collection name (default from config)

    Returns:
        list of dicts: {content, score, metadata}
    """
    client = _get_client()
    if client is None:
        return []

    config = current_app.config
    collection_name = collection or config.get("CHROMA_COLLECTION", "looma_knowledge")

    try:
        coll = client.get_or_create_collection(collection_name)
        results = coll.query(
            query_texts=[query],
            n_results=min(n_results, max(1, n_results)),
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        ids = results.get("ids", [[]])[0]

        output = []
        for i in range(len(documents)):
            # ChromaDB distance → similarity score (1 - distance for cosine)
            score = 1 - distances[i] if distances else None
            output.append({
                "id": ids[i] if ids else None,
                "content": documents[i],
                "score": round(score, 4) if score else None,
                "metadata": metadatas[i] if metadatas else {},
            })
        return output

    except Exception as e:
        logger.warning(f"ChromaDB search failed: {e}")
        return []


def add_documents(texts: list[str], metadatas: list[dict] | None = None,
                   ids: list[str] | None = None, collection: str | None = None):
    """Add documents to ChromaDB collection.

    Args:
        texts: list of text chunks to add
        metadatas: optional list of metadata dicts
        ids: optional list of unique IDs
        collection: collection name (default from config)
    """
    client = _get_client()
    if client is None:
        return

    config = current_app.config
    collection_name = collection or config.get("CHROMA_COLLECTION", "looma_knowledge")

    try:
        import uuid as _uuid
        coll = client.get_or_create_collection(collection_name)
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in texts]
        if metadatas is None:
            metadatas = [{} for _ in texts]

        coll.add(documents=texts, metadatas=metadatas, ids=ids)
        logger.info(f"Added {len(texts)} chunks to {collection_name}")
    except Exception as e:
        logger.error(f"ChromaDB add failed: {e}")


def get_collection_stats(collection: str | None = None) -> dict:
    """Get collection stats (count, name)."""
    client = _get_client()
    if client is None:
        return {"count": 0, "name": "unavailable"}

    config = current_app.config
    collection_name = collection or config.get("CHROMA_COLLECTION", "looma_knowledge")

    try:
        coll = client.get_or_create_collection(collection_name)
        return {"count": coll.count(), "name": collection_name}
    except Exception:
        return {"count": 0, "name": collection_name}


# ============================================
# Poetry ChromaDB — independent embedded client
# ============================================
# Poetry data is a static pre-built ChromaDB embedded directory.
# It is always read via PersistentClient, never via remote server,
# so poetry search works regardless of CHROMA_MODE.

_poetry_client = None
_poetry_client_lock = False


def _get_poetry_client():
    """Get or initialize the poetry ChromaDB embedded client.

    Reads from POETRY_CHROMA_PATH (default: data/poetry_full).
    Falls back to a writable temp copy if the source dir is read-only.
    """
    global _poetry_client, _poetry_client_lock

    if _poetry_client is not None:
        return _poetry_client

    # Prevent re-entrant init storms
    if _poetry_client_lock:
        return None
    _poetry_client_lock = True

    try:
        from pathlib import Path
        config = current_app.config
        poetry_path = Path(config.get("POETRY_CHROMA_PATH", "data/poetry_full"))

        # Resolve relative path against the app root (where DATABASE_PATH lives)
        if not poetry_path.is_absolute():
            db_root = Path(config.get("DATABASE_PATH", "data/looma.db")).parent
            poetry_path = (db_root / poetry_path).resolve()

        if not poetry_path.is_dir():
            logger.warning(f"Poetry ChromaDB dir not found: {poetry_path}")
            _poetry_client_lock = False
            return None

        import chromadb
        import os
        import tempfile
        import shutil

        # ChromaDB PersistentClient needs write access (sqlite3 lock).
        # If the source is read-only (Docker :ro mount), copy to tmp.
        sqlite_file = poetry_path / "chroma.sqlite3"
        if sqlite_file.exists() and not os.access(str(sqlite_file), os.W_OK):
            work_dir = tempfile.mkdtemp(prefix="poetry_chroma_")
            logger.info(f"Poetry ChromaDB is read-only, copying to {work_dir}")
            shutil.copytree(str(poetry_path), work_dir, dirs_exist_ok=True)
            _poetry_client = chromadb.PersistentClient(path=work_dir)
        else:
            _poetry_client = chromadb.PersistentClient(path=str(poetry_path))

        logger.info(f"Poetry ChromaDB client initialized (path={poetry_path})")
    except ImportError:
        logger.warning("chromadb not installed — poetry search unavailable")
    except Exception as e:
        logger.error(f"Poetry ChromaDB init failed: {e}")
    finally:
        _poetry_client_lock = False

    return _poetry_client


def search_poetry_chroma(query: str, n_results: int = 5) -> list[dict]:
    """Search the poetry ChromaDB collection via embedded PersistentClient.

    This is independent of CHROMA_MODE — always uses the local embedded
    poetry dataset, never the remote ChromaDB server.

    Args:
        query: search query text
        n_results: number of results to return

    Returns:
        list of dicts: {content, score, metadata}
    """
    client = _get_poetry_client()
    if client is None:
        return []

    try:
        # Normalize Simplified -> Traditional before embedding so query vector
        # aligns with the Traditional corpus (see src/utils/textnorm.py).
        from src.utils.textnorm import to_traditional

        normalized = to_traditional(query)
        coll = client.get_collection("poetry_full")
        results = coll.query(
            query_texts=[normalized],
            n_results=min(n_results, max(1, n_results)),
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        ids = results.get("ids", [[]])[0]

        output = []
        for i in range(len(documents)):
            score = 1 - distances[i] if distances else None
            output.append({
                "id": ids[i] if ids else None,
                "content": documents[i],
                "score": round(score, 4) if score else None,
                "metadata": metadatas[i] if metadatas else {},
            })
        return output

    except Exception as e:
        logger.warning(f"Poetry ChromaDB search failed: {e}")
        return []
