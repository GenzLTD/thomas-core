"""母舰答题会话。表结构与 looma product_schema.quiz_sessions 一致。

核的 CoreDB 只建 core 7 表。quiz_sessions 留在产品 DDL 里，这里在第一次
答题时 CREATE TABLE IF NOT EXISTS，这样独立核和已经有这张表的 looma.db 都能写。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

_SHA_TZ = timezone(timedelta(hours=8))

_DDL = """
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    questions_json  TEXT NOT NULL DEFAULT '[]',
    current_index   INTEGER NOT NULL DEFAULT 0,
    answers_json    TEXT NOT NULL DEFAULT '[]',
    total_score     INTEGER NOT NULL DEFAULT 0,
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count   INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    result_type     TEXT DEFAULT '',
    insights_json   TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""


def _now() -> str:
    return datetime.now(_SHA_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")


def ensure_table(db) -> None:
    with db.get_conn() as conn:
        conn.execute(_DDL)


def create_quiz_session(db, user_id: str, questions_json: str) -> dict:
    questions = json.loads(questions_json)
    session_id = str(uuid.uuid4())
    ensure_table(db)
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO quiz_sessions
               (id, user_id, questions_json, total_questions, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (session_id, user_id, questions_json, len(questions)),
        )
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else {}


def get_quiz_session(db, session_id: str) -> dict | None:
    ensure_table(db)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def submit_quiz_answer(db, session_id: str, question_id: str,
                       option_ids: list, score: int) -> dict | None:
    ensure_table(db)
    with db.get_conn() as conn:
        session = conn.execute(
            "SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not session:
            return None
        current = dict(session)
        answers = json.loads(current["answers_json"] or "[]")
        answers.append({
            "question_id": question_id,
            "option_ids": option_ids,
            "score": score,
        })
        new_index = current["current_index"] + 1
        new_score = current["total_score"] + score
        new_correct = current["correct_count"] + (1 if score > 0 else 0)
        completed = new_index >= current["total_questions"]
        conn.execute(
            """UPDATE quiz_sessions SET
               answers_json = ?, current_index = ?, total_score = ?,
               correct_count = ?, status = ?, completed_at = ?
               WHERE id = ?""",
            (
                json.dumps(answers, ensure_ascii=False),
                new_index,
                new_score,
                new_correct,
                "completed" if completed else "active",
                _now() if completed else None,
                session_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def complete_quiz_session(db, session_id: str, result_type: str = "",
                          insights_json: str = "[]") -> dict | None:
    ensure_table(db)
    with db.get_conn() as conn:
        conn.execute(
            """UPDATE quiz_sessions SET
               status = 'completed', result_type = ?, insights_json = ?,
               completed_at = ?
               WHERE id = ?""",
            (result_type, insights_json, _now(), session_id),
        )
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_quiz_history(db, user_id: str, limit: int = 20) -> list:
    ensure_table(db)
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, total_score, total_questions, correct_count,
               result_type, status, created_at, completed_at
               FROM quiz_sessions
               WHERE user_id = ? AND status = 'completed'
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
