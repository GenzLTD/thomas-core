"""画像引擎四个方法。SQL 先落，Chroma 失败只记日志。"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import current_app

from src.thomas_core.db import schema_loader
from src.thomas_core.profile import chroma_index

logger = logging.getLogger("looma.profile")

DOMAINS = frozenset({"career", "learning", "life", "social", "health", "creative"})
# v4：健康 / 社交 / 生活不进企业可见集。写入时就钉死，不留给读路径补救。
ENTERPRISE_NEVER = frozenset({"health", "social", "life"})
_PAYLOAD_KEYS = (
    "result_type",
    "total_score",
    "correct_count",
    "total_questions",
    "session_id",
)


class ProfileEventRejected(ValueError):
    """身份元数据或域不齐，拒绝写入。"""


def record_profile_event(
    *,
    user_id: str,
    domain: str,
    event_type: str,
    payload: dict,
    source: str,
    consent_scope: str,
    enterprise_visible: int = 0,
    db_path: str | None = None,
) -> dict:
    """写入一条追加事件，并尽力同步到 profile_context。"""
    user_id = (user_id or "").strip()
    domain = (domain or "").strip()
    event_type = (event_type or "").strip()
    consent_scope = (consent_scope or "").strip()
    if not user_id or not event_type or not consent_scope:
        raise ProfileEventRejected("user_id, event_type, consent_scope are required")
    if domain not in DOMAINS:
        raise ProfileEventRejected(f"unknown domain: {domain}")
    if not isinstance(payload, dict):
        raise ProfileEventRejected("payload must be an object")

    visible = 0 if domain in ENTERPRISE_NEVER else (1 if int(enterprise_visible) else 0)
    event_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path = db_path or _db_path()
    schema_loader.ensure_scope(path, "profile")

    with _connect(path) as conn:
        conn.execute(
            """INSERT INTO profile_events
               (id, user_id, domain, event_type, payload_json, source,
                consent_scope, enterprise_visible, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, domain, event_type, payload_json, source or "",
             consent_scope, visible, created_at),
        )

    metadata = {"user_id": user_id, "domain": domain, "consent_scope": consent_scope}
    chroma_ok = chroma_index.upsert_event(path, event_id, _document(domain, event_type, payload), metadata)
    return {
        "id": event_id,
        "user_id": user_id,
        "domain": domain,
        "event_type": event_type,
        "consent_scope": consent_scope,
        "enterprise_visible": visible,
        "created_at": created_at,
        "chroma_ok": chroma_ok,
    }


def record_quiz_result(
    *,
    user_id: str,
    session_id: str,
    result_type: str,
    total_score: int,
    correct_count: int,
    total_questions: int,
) -> dict:
    """答题结算是 v0 的唯一事件源。授权快照用 game_quiz，企业不可见。"""
    return record_profile_event(
        user_id=user_id,
        domain="learning",
        event_type="quiz_result",
        source="game",
        consent_scope="game_quiz",
        enterprise_visible=0,
        payload={
            "session_id": session_id,
            "result_type": result_type,
            "total_score": total_score,
            "correct_count": correct_count,
            "total_questions": total_questions,
        },
    )


def get_profile_context(user_id: str, scopes: list[str] | None = None, db_path: str | None = None) -> dict:
    path = db_path or _db_path()
    domains = [item for item in (scopes or []) if item in DOMAINS]
    return {
        "events": _events(path, user_id, domains),
        "vectors": chroma_index.vectors_for_user(path, user_id, domains or None),
    }


def delete_user_data(user_id: str, db_path: str | None = None) -> dict:
    """删这个用户的画像事实和对应向量，不动账号本身。"""
    path = db_path or _db_path()
    schema_loader.ensure_scope(path, "profile")
    with _connect(path) as conn:
        cur = conn.execute("DELETE FROM profile_events WHERE user_id = ?", (user_id,))
        sql_deleted = cur.rowcount
    return {
        "user_id": user_id,
        "sql_deleted": sql_deleted,
        "chroma_deleted": chroma_index.delete_user(path, user_id),
    }


def export_user_data(user_id: str, db_path: str | None = None) -> dict:
    path = db_path or _db_path()
    events = _events(path, user_id, [])
    vectors = chroma_index.vectors_for_user(path, user_id, None)
    return {
        "user_id": user_id,
        "events": events,
        "vectors": vectors,
        "chroma_ok": chroma_index.chroma_ready(path),
    }


def _events(path: str, user_id: str, domains: list[str]) -> list[dict]:
    schema_loader.ensure_scope(path, "profile")
    sql = "SELECT * FROM profile_events WHERE user_id = ?"
    args: list = [user_id]
    if domains:
        marks = ",".join("?" for _ in domains)
        sql += f" AND domain IN ({marks})"
        args.extend(domains)
    sql += " ORDER BY created_at"
    with _connect(path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_dict(row) for row in rows]


def _document(domain: str, event_type: str, payload: dict) -> str:
    visible = {key: payload[key] for key in _PAYLOAD_KEYS if key in payload}
    return f"{domain} {event_type} " + json.dumps(visible, ensure_ascii=False, sort_keys=True)


def _db_path() -> str:
    return current_app.config["DATABASE_PATH"]


@contextmanager
def _connect(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        item["payload"] = {}
    return item
