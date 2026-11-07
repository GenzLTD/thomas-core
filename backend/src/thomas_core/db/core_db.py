"""核的数据库面（刀 5c：从 `src/db/manager.py` 里切出的 26 个方法）。

为什么切：`DatabaseManager`（169 个成员 / 3,530 行）是**核+产品的合订本** —— 里面既有
`users`/`user_identities`/`quota_records`/`audit_logs` 这些核写权表，也有 jobs / resume /
fleet / payment / enterprise 等产品查询。核如果继续 `from src.db.manager import DatabaseManager`，
独立发版 split 后新仓会把 4.7k 行产品 DB 层一起拖走，且核进程握着产品表写权 —— 违背 R1。

口径（只认人）：
- `CoreDB` 只碰 core_schema 的 7 表（外加 quota_records / boost_* / query_logs / usage_logs
  这几张被 ask 计量链路共用的表）；
- 建表走 `schema_loader.ensure_scope`（core 优先，legacy 时补 product），**不搬** `init_schema`
  的全量 DDL 与 migration —— 那是产品的活，留在 `DatabaseManager`；
- `DatabaseManager(CoreDB)` 继承本类，宿主调用面零改动（26 个方法的位置从 manager 移到此处，
  签名 / 行为 / SQL 一字未改）。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime

from src.thomas_core.db import schema_loader

logger = logging.getLogger(__name__)


def _dt_now():
    """Helper for consistent datetime strings."""
    return datetime.now()


def email_hash(email: str | None) -> str | None:
    """Canonical email hash shared with DemoPPI / GFCC (Bridge 2/3).

    Both sides compute sha256 of the lowercased, trimmed email as lowercase hex
    so PlanetX (Python) and DemoPPI (TypeScript) yield identical digests for the
    same mailbox. Returns None for empty email (miniprogram-only users).
    """
    if not email:
        return None
    normalized = email.lower().strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()



class CoreDB:
    """核的 SQLite 连接面 + 身份 / 配额 / 查询计量方法（只读写 core 面）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        if not self._is_memory:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    def _connect(self):
        """Create a new SQLite connection."""
        if self._is_memory:
            # Use URI format to share in-memory DB across connections
            conn = sqlite3.connect(
                "file:memdb1?mode=memory&cache=shared",
                uri=True,
            )
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")  # 5s busy-wait 缓解 SQLITE_BUSY
        return conn

    def init_core_schema(self, include_product: bool | None = None) -> dict:
        """确保 core schema 存在（幂等）；legacy 模式把 product scope 也建上。

        与 `DatabaseManager.init_schema()` 的区别：不执行产品侧的 ALTER migration
        （那是产品库的演进，属于宿主）。返回 core scope 的 ensure 结果。
        """
        if include_product is None:
            include_product = not schema_loader.split_enabled()
        info = schema_loader.ensure_scope(self.db_path, "core")
        if include_product:
            schema_loader.ensure_scope(self.db_path, "product")
        return info

    @contextmanager
    def get_conn(self):
        """Get a SQLite connection with WAL mode enabled."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_user(self, email=None, password_hash=None, wechat_openid=None, name=""):
        """Create a new user. email and wechat_openid are both nullable."""
        user_id = str(uuid.uuid4())
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO users (id, email, email_hash, password_hash, wechat_openid,
                   principal_sub, name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, email, email_hash(email), password_hash, wechat_openid,
                 user_id, name)
            )
        return user_id

    def set_principal_sub(self, user_id: str, principal_sub: str):
        """Persist GFCC principal.sub (or bootstrap equivalent) for a user."""
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE users SET principal_sub = ?, updated_at = datetime('now') WHERE id = ?",
                (principal_sub, user_id),
            )

    def get_user_by_email(self, email: str):
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def get_user_by_openid(self, openid: str):
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE wechat_openid = ?", (openid,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str):
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_supabase_uid(self, supabase_uid: str):
        """Resolve a looma user by Supabase Auth user UUID (THOMAS unified identity)."""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE supabase_uid = ?", (supabase_uid,)
            ).fetchone()
        return dict(row) if row else None

    def bind_supabase_to_user(self, user_id: str, supabase_uid: str):
        """Link a Supabase Auth UUID to an existing looma user (legacy account binding)."""
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE users SET supabase_uid = ?, updated_at = datetime('now') WHERE id = ?",
                (supabase_uid, user_id),
            )

    def get_or_create_user_by_supabase(self, supabase_uid: str, email: str = "",
                                       name: str = "", wechat_openid: str = None):
        """Find-or-create a looma user for a Supabase identity.

        1. supabase_uid 已映射 → 返回现有用户
        2. email 匹配存量用户（排除 thomas.local 占位邮箱）→ 绑定 supabase_uid（存量迁移）
        3. 否则创建新用户并绑定

        Returns (user_dict, created_bool).
        """
        user = self.get_user_by_supabase_uid(supabase_uid)
        if user:
            return user, False

        email = (email or "").strip().lower()
        if email and not email.endswith(".thomas.local"):
            legacy = self.get_user_by_email(email)
            if legacy:
                self.bind_supabase_to_user(legacy["id"], supabase_uid)
                if name and not legacy.get("name"):
                    with self.get_conn() as conn:
                        conn.execute(
                            "UPDATE users SET name = ?, updated_at = datetime('now') WHERE id = ?",
                            (name, legacy["id"]),
                        )
                return self.get_user_by_id(legacy["id"]), False

        user_id = str(uuid.uuid4())
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO users (id, email, email_hash, supabase_uid, wechat_openid,
                principal_sub, name)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, email or None, email_hash(email or None), supabase_uid,
                 wechat_openid, user_id, name),
            )
        return self.get_user_by_id(user_id), True

    def bind_wechat_to_user(self, user_id: str, wechat_openid: str):
        """Bind a WeChat openid to an existing user (cross-platform account linking)."""
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE users SET wechat_openid = ?, updated_at = datetime('now') WHERE id = ?",
                (wechat_openid, user_id)
            )

    def get_user_by_identity(self, provider: str, provider_uid: str):
        """Find a user by a third-party identity (google sub, apple sub, wechat openid)."""
        with self.get_conn() as conn:
            row = conn.execute(
                """SELECT u.* FROM users u
                   JOIN user_identities ui ON u.id = ui.user_id
                   WHERE ui.provider = ? AND ui.provider_uid = ?""",
                (provider, provider_uid)
            ).fetchone()
        return dict(row) if row else None

    def link_identity(self, user_id: str, provider: str, provider_uid: str,
                      provider_email: str = "", provider_name: str = "",
                      metadata_json: str = "{}"):
        """Link a third-party identity to an existing user.
        If the identity is already linked to a different user, raises ValueError."""
        with self.get_conn() as conn:
            existing = conn.execute(
                "SELECT user_id FROM user_identities WHERE provider = ? AND provider_uid = ?",
                (provider, provider_uid)
            ).fetchone()
            if existing and existing["user_id"] != user_id:
                raise ValueError(f"Identity {provider}:{provider_uid} is already linked to another user")
            if existing:
                return  # already linked to this user, idempotent
            conn.execute(
                """INSERT INTO user_identities (id, user_id, provider, provider_uid,
                   provider_email, provider_name, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), user_id, provider, provider_uid,
                 provider_email, provider_name, metadata_json)
            )

    def get_user_identities(self, user_id: str):
        """List all identities linked to a user."""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT provider, provider_uid, provider_email, provider_name FROM user_identities WHERE user_id = ?",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_or_create_user_by_identity(self, provider: str, provider_uid: str,
                                       email: str = "", name: str = "",
                                       metadata_json: str = "{}"):
        """Find or create a user by third-party identity.
        If the identity exists, return the linked user.
        If not, create a new user + link the identity, return the new user.
        If email matches an existing user, link the identity to that user instead."""
        # 1. Check if identity already linked
        user = self.get_user_by_identity(provider, provider_uid)
        if user:
            return user, False  # existing user, not newly created

        # 2. Check if email matches an existing user (account merge)
        if email:
            user = self.get_user_by_email(email)
            if user:
                self.link_identity(user["id"], provider, provider_uid, email, name, metadata_json)
                return user, False

        # 3. Create new user + link identity
        user_id = str(uuid.uuid4())
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO users (id, email, email_hash, principal_sub, name)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, email or None, email_hash(email or None), user_id, name)
            )
            conn.execute(
                """INSERT INTO user_identities (id, user_id, provider, provider_uid,
                   provider_email, provider_name, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), user_id, provider, provider_uid,
                 email, name, metadata_json)
            )
        return self.get_user_by_id(user_id), True  # newly created

    def log_usage(self, user_id: str, endpoint: str, tokens_used: int = 0):
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO usage_logs (id, user_id, endpoint, tokens_used)
                   VALUES (?, ?, ?, ?)""",
                (str(uuid.uuid4()), user_id, endpoint, tokens_used)
            )

    def get_daily_usage_count(self, user_id: str) -> int:
        with self.get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM usage_logs
                   WHERE user_id = ? AND date(created_at) = date('now')""",
                (user_id,)
            ).fetchone()
        return row["cnt"] if row else 0

    def get_quota(self, user_id: str, resource: str, date: str):
        """Get quota record for a specific user + resource + date."""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM quota_records WHERE user_id=? AND resource=? AND date=?",
                (user_id, resource, date),
            ).fetchone()
        return dict(row) if row else None

    def consume_quota(self, user_id: str, resource: str, date: str, limit: int) -> bool:
        """Consume 1 quota unit. Returns True=success, False=exceeded."""
        with self.get_conn() as conn:
            existing = conn.execute(
                "SELECT used FROM quota_records WHERE user_id=? AND resource=? AND date=?",
                (user_id, resource, date),
            ).fetchone()
            if existing:
                used = existing[0]
                if used >= limit:
                    return False
                conn.execute(
                    "UPDATE quota_records SET used=used+1 WHERE user_id=? AND resource=? AND date=?",
                    (user_id, resource, date),
                )
            else:
                conn.execute(
                    "INSERT INTO quota_records (user_id, resource, date, used, daily_limit) VALUES (?, ?, ?, 1, ?)",
                    (user_id, resource, date, limit),
                )
        return True

    def refund_quota(self, user_id: str, resource: str, date: str) -> bool:
        """Refund 1 daily quota unit (best-effort). Returns True if decremented."""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT used FROM quota_records WHERE user_id=? AND resource=? AND date=?",
                (user_id, resource, date),
            ).fetchone()
            if not row or row[0] <= 0:
                return False
            conn.execute(
                "UPDATE quota_records SET used=used-1 WHERE user_id=? AND resource=? AND date=? AND used>0",
                (user_id, resource, date),
            )
        return True

    def get_boost_credit_remaining(self, user_id: str) -> int:
        """Get total remaining boost credits for a user."""
        with self.get_conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(credits - credits_used), 0) AS remaining
                   FROM boost_packs
                   WHERE user_id=? AND status='active'
                     AND expires_at > datetime('now')""",
                (user_id,),
            ).fetchone()
        return row[0] if row else 0

    def consume_boost_credit(self, user_id: str, resource: str) -> bool:
        """Consume 1 boost credit from the earliest-expiring active pack."""
        with self.get_conn() as conn:
            pack = conn.execute(
                """SELECT * FROM boost_packs
                   WHERE user_id=? AND status='active'
                     AND expires_at > datetime('now')
                     AND credits_used < credits
                   ORDER BY expires_at ASC LIMIT 1""",
                (user_id,),
            ).fetchone()

            if not pack:
                return False

            pack_dict = dict(pack)
            pack_id = pack_dict["id"]

            conn.execute(
                "UPDATE boost_packs SET credits_used=credits_used+1 WHERE id=?",
                (pack_id,),
            )
            conn.execute(
                "INSERT INTO boost_consumptions (user_id, boost_pack_id, resource, credits_consumed) VALUES (?, ?, ?, 1)",
                (user_id, pack_id, resource),
            )
            if pack_dict["credits_used"] + 1 >= pack_dict["credits"]:
                conn.execute("UPDATE boost_packs SET status='exhausted' WHERE id=?", (pack_id,))
        return True

    def log_query(self, query_text: str, provider: str, response_time_ms: float,
                  chunk_count: int = 0, user_id: str | None = None,
                  intent_label: str | None = None):
        """Log a query for the data flywheel."""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO query_logs (query_text, provider, response_time_ms, chunk_count, user_id, intent_label, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (query_text, provider, response_time_ms, chunk_count, user_id, intent_label,
                 _dt_now().isoformat())
            )

    def rate_query(self, query_id: int, rating: int):
        """Rate a query (1-5)."""
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE query_logs SET rating=? WHERE id=?",
                (rating, query_id),
            )

    def get_last_query_id(self, user_id: str) -> int | None:
        """Get the ID of the user's most recent query."""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM query_logs WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return row[0] if row else None
