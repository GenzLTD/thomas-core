"""Scope-aware schema loader（Phase 1 刀 5：把两份 DDL 接进启动流程）。

分工（RFC 裁决 2 / R1）：
- `core`    → `core_schema.sql`（7 表：users / user_identities / consents / audit_logs / signal_ingest|outbox|dlq）
- `product` → `product_schema.sql`（50 表 + 3 个 signal_* 只读视图）

约束：
1. **同库不拆文件**——两个 scope 写同一个 `looma.db`，只是建表权分开；
2. product 侧外键 / 视图依赖 core 的 `users`，故 **core 必须先建**（split 模式下宿主启动时校验，缺则 fail-fast 给可执行提示）；
3. 每次 ensure 记录 `schema_meta(scope, version, applied_at)`，`version = sha256(LF 归一后的 sql)[:12]`；
   文件变了而库没迁移 → 默认告警（drift），`THOMAS_SCHEMA_STRICT=1` 时直接抛错。

行为不变纪律：`ensure_scope` 只做 `CREATE ... IF NOT EXISTS`（DDL 文件本身如此），不改任何既有表结构，
不搬 manager.py 的 migration 逻辑；legacy 模式（`THOMAS_SCHEMA_SPLIT=0`）完全走原 `DatabaseManager.init_schema()`。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).resolve().parent


def _sql_dir() -> Path:
    """DDL 目录：核内 `thomas_core/db/` 优先，其次仓内 `src/db/`。

    两份布局都要成立 —— 刀 5d 把 loader 搬进核，但 `.sql` 仍留在 `src/db/`
    （独立核仓沿用同一相对位置）。判据是 `core_schema.sql` 是否在同级。
    """
    candidates = [_MODULE_DIR]
    if len(_MODULE_DIR.parents) >= 2:
        candidates.append(_MODULE_DIR.parents[1] / "db")
    for cand in candidates:
        if (cand / "core_schema.sql").is_file():
            return cand
    return _MODULE_DIR


_DB_DIR = _sql_dir()
SCOPE_FILES = {
    "core": _DB_DIR / "core_schema.sql",
    "product": _DB_DIR / "product_schema.sql",
}
# core 侧「在不在」的判定锚（宿主 split 启动时校验用）
CORE_ANCHOR_TABLES = (
    "users",
    "user_identities",
    "consents",
    "audit_logs",
    "signal_ingest",
    "signal_outbox",
    "signal_dlq",
)

_META_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    scope      TEXT PRIMARY KEY,
    version    TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

# CREATE [UNIQUE] TABLE|INDEX|VIEW|TRIGGER 后面补 IF NOT EXISTS（已带则跳过）
_CREATE_RE = re.compile(
    r"CREATE\s+(UNIQUE\s+)?(TABLE|INDEX|VIEW|TRIGGER)\s+(?!IF\s+NOT\s+EXISTS\b)",
    re.IGNORECASE,
)


class SchemaDriftError(RuntimeError):
    """DDL 文件版本与库内记录不一致（且 THOMAS_SCHEMA_STRICT=1）。"""


def sql_text(scope: str) -> str:
    """返回**幂等化**后的 DDL。

    `sqlite_master.sql` 保存的建表语句会丢掉 `IF NOT EXISTS`，而两份 schema 正是从
    实库 `sqlite_master` 抽出来的 —— 因此必须在执行前补回，否则已有库上会报
    `table users already exists`。
    """
    raw = SCOPE_FILES[scope].read_text(encoding="utf-8")
    return _CREATE_RE.sub(
        lambda m: f"CREATE {m.group(1) or ''}{m.group(2)} IF NOT EXISTS ", raw
    )


def file_version(scope: str) -> str:
    """DDL 文件版本 = `sha256[:12]`，**按 LF 归一后**再算。

    为什么必须归一：仓库里的 blob 存的是 LF，但 Windows（`core.autocrlf=true`）检出后
    工作树是 CRLF。若直接对字节做 sha256，同一个 DDL 在两平台会算出两个版本号 ——
    Linux/CI 建的库拿到 Windows 跑就会被误判 drift（`THOMAS_SCHEMA_STRICT=1` 时直接
    抛 `SchemaDriftError` 起不来）。归一后两端同值，且与既有库记录一致。
    """
    raw = SCOPE_FILES[scope].read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()[:12]


def split_enabled(default: str = "1") -> bool:
    return os.getenv("THOMAS_SCHEMA_SPLIT", default).strip().lower() in ("1", "true", "yes", "on")


def core_ready(db_path: str) -> bool:
    """core 的 7 张锚表是否都在（不建表，只探测）。"""
    if db_path == ":memory:":
        return False
    if not os.path.exists(db_path):
        return False
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    names = {r[0] for r in rows}
    return all(t in names for t in CORE_ANCHOR_TABLES)


def is_empty(db_path: str) -> bool:
    """库内是否还没有任何业务表（`schema_meta` 与 `sqlite_*` 不算）。

    用于区分**冷启动**（空库，谁来建都行）与**指错库**（非空但缺 core，必须 fail-fast）。
    """
    if db_path == ":memory:" or not os.path.exists(db_path):
        return True
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' AND name != 'schema_meta'"
        ).fetchall()
    finally:
        conn.close()
    return not rows


def ensure_scope(db_path: str, scope: str, strict: bool | None = None) -> dict:
    """确保某 scope 的对象存在（幂等），并记录/校验版本。

    返回 {scope, version, drift, tables, views, applied}。
    """
    if scope not in SCOPE_FILES:
        raise ValueError(f"unknown schema scope: {scope}")
    if db_path == ":memory:":
        # 内存库：每个连接是独立的，文件级 ensure 无意义 → 由调用方走 legacy init
        return {"scope": scope, "version": None, "drift": False,
                "tables": 0, "views": 0, "applied": False, "skipped": "memory-db"}

    if strict is None:
        strict = os.getenv("THOMAS_SCHEMA_STRICT", "0").strip().lower() in ("1", "true", "yes", "on")

    version = file_version(scope)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_META_DDL)
        conn.commit()
        row = conn.execute("SELECT version FROM schema_meta WHERE scope = ?", (scope,)).fetchone()
        drift = bool(row and row[0] != version)
        if drift:
            logger.warning(
                "[schema] drift scope=%s db=%s file=%s db_recorded=%s — 需迁移脚本对齐",
                scope, db_path, version, row[0],
            )
        conn.executescript(sql_text(scope))
        conn.execute(
            """INSERT INTO schema_meta (scope, version, applied_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(scope) DO UPDATE SET version = excluded.version,
                                                applied_at = excluded.applied_at""",
            (scope, version),
        )
        conn.commit()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        views = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='view'"
        ).fetchone()[0]
    finally:
        conn.close()

    if drift and strict:
        raise SchemaDriftError(
            f"schema drift on scope={scope}: db has older/newer version, file={version}"
        )
    logger.info("[schema] ensure scope=%s version=%s tables=%s views=%s drift=%s",
                scope, version, tables, views, drift)
    return {"scope": scope, "version": version, "drift": drift,
            "tables": tables, "views": views, "applied": True}
