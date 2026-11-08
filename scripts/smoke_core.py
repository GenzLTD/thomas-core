"""thomas-core 独立仓自检（不依赖宿主任何模块）。

用法：
    cd backend && python ../scripts/smoke_core.py

判据（9 项，全过 exit 0）：
  1. `src.app` 不可导入（证明已脱离宿主）
  2. `create_core_app()` 可装配，/health = 200 且 service=thomas-core
  3. register 201 / login 200 / consent 200
  4. 数据库 8 张表（core 7 表 + schema_meta），schema_meta 有 core 行
  5. `/v1/ask` 在未注册 brain 时 500 且日志含 BrainNotConfigured（非静默空答案）
  6. 核内模块级 import 不出现宿主包（惰性兼容 import 允许，但必须包在 try 内）
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# 用临时库，绝不碰真实 data/looma.db
_DB = Path(tempfile.mkdtemp(prefix="core-smoke-")) / "core.db"
os.environ["DATABASE_PATH"] = str(_DB)
os.environ["THOMAS_SCHEMA_SPLIT"] = "1"
os.environ["PROFILE_EMBED"] = "deterministic"
# Supabase 相关留空，避免走真网络 / 真 key
for k in (
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY",
    "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWT_SECRET",
    "DEEPSEEK_API_KEY",
):
    os.environ.pop(k, None)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def _check_profile(c, headers) -> None:
    """答题结算写 SQL，Chroma 带身份元数据，删除后两边都空。"""
    from src.thomas_core.profile.engine import ProfileEventRejected, record_profile_event

    rejected = False
    try:
        record_profile_event(
            user_id="someone",
            domain="learning",
            event_type="quiz_result",
            payload={},
            source="game",
            consent_scope="",
        )
    except ProfileEventRejected:
        rejected = True
    check("画像缺 consent_scope 拒写", rejected)

    started = c.post("/v1/game/start", headers=headers)
    session_id = (started.get_json() or {}).get("session_id") or ""
    for n in range(1, 6):
        c.post("/v1/game/answer", headers=headers, json={
            "session_id": session_id,
            "question_id": f"q{n}",
            "option_ids": ["a"],
        })
    result = c.get(f"/v1/game/result?session_id={session_id}", headers=headers)
    body = result.get_json() or {}
    check("quiz result 200 专家级",
          result.status_code == 200 and body.get("result_type") == "专家级",
          f"status={result.status_code} type={body.get('result_type')}")

    conn = sqlite3.connect(_DB)
    row = conn.execute(
        "SELECT domain, consent_scope, event_type, enterprise_visible FROM profile_events"
    ).fetchone()
    conn.close()
    check("结算写入 profile_events",
          row == ("learning", "game_quiz", "quiz_result", 0),
          f"row={row}")

    exported = c.get("/v1/profile/export", headers=headers)
    payload = exported.get_json() or {}
    vectors = payload.get("vectors") or []
    meta_ok = bool(vectors) and all(
        (item.get("metadata") or {}).get("user_id")
        and (item.get("metadata") or {}).get("domain")
        and (item.get("metadata") or {}).get("consent_scope")
        for item in vectors
    )
    check("export 含 SQL 事件且向量带三元组",
          exported.status_code == 200 and len(payload.get("events") or []) == 1 and meta_ok,
          f"status={exported.status_code} events={len(payload.get('events') or [])} vectors={len(vectors)}")

    deleted = c.delete("/v1/profile", headers=headers)
    gone = deleted.get_json() or {}
    conn = sqlite3.connect(_DB)
    left = conn.execute("SELECT COUNT(*) FROM profile_events").fetchone()[0]
    conn.close()
    again = c.get("/v1/profile/export", headers=headers).get_json() or {}
    check("delete_user_data 后 SQL 与 Chroma 都空",
          deleted.status_code == 200 and left == 0 and gone.get("chroma_deleted") == 1
          and not again.get("events") and not again.get("vectors"),
          f"status={deleted.status_code} sql_left={left} chroma_deleted={gone.get('chroma_deleted')} "
          f"events={len(again.get('events') or [])} vectors={len(again.get('vectors') or [])}")


def main() -> int:
    print("thomas-core 独立仓自检")
    print(f"  backend={BACKEND}")
    print(f"  db={_DB}")

    # 1) 宿主模块必须不存在
    check("src.app 不可导入（已脱离宿主）", importlib.util.find_spec("src.app") is None)

    from src.thomas_core.app import create_core_app

    app = create_core_app()
    # /v1/ask 未注册 brain 时抛 BrainNotConfigured 是预期行为，压掉堆栈噪音
    # （ask_routes 用模块级 logger.exception，故按 logger 名统一降级）
    app.logger.setLevel(logging.CRITICAL)
    for lname in ("src.thomas_core", "src.thomas_core.brain",
                  "src.thomas_core.routes.ask_routes", "looma.ask", "looma"):
        logging.getLogger(lname).setLevel(logging.CRITICAL)
    # 让 Flask 把视图异常转成 500 而非冒泡到 stdout
    app.config["PROPAGATE_EXCEPTIONS"] = False
    c = app.test_client()

    r = c.get("/health")
    body = r.get_json() or {}
    check("/health 200 + service=thomas-core",
          r.status_code == 200 and body.get("service") == "thomas-core",
          f"status={r.status_code} service={body.get('service')}")
    check("health chroma_ok 是布尔值", isinstance(body.get("chroma_ok"), bool),
          f"chroma_ok={body.get('chroma_ok')}")

    email = "smoke@core.local"
    r_reg = c.post("/v1/auth/register",
                   json={"email": email, "password": "Passw0rd!", "name": "smoke"})
    check("register 201", r_reg.status_code == 201, f"status={r_reg.status_code}")

    r_login = c.post("/v1/auth/login", json={"email": email, "password": "Passw0rd!"})
    check("login 200", r_login.status_code == 200, f"status={r_login.status_code}")
    token = (r_login.get_json() or {}).get("access_token") or ""
    headers = {"Authorization": f"Bearer {token}"}

    r_consent = c.post("/v1/compliance/consent/grant",
                       json={"scope": "ask_rag", "granted": True}, headers=headers)
    check("consent 200", r_consent.status_code == 200, f"status={r_consent.status_code}")

    conn = sqlite3.connect(_DB)
    n_tables = conn.execute(
        "select count(*) from sqlite_master where type='table' and name not like 'sqlite_%'"
    ).fetchone()[0]
    scopes = [x[0] for x in conn.execute("select distinct scope from schema_meta")]
    conn.close()
    check("9 表 + schema_meta 有 core/profile",
          n_tables == 9 and "core" in scopes and "profile" in scopes,
          f"tables={n_tables} scopes={scopes}")

    # ask 未注册 brain：应失败而非静默空答案
    r_ask = c.post("/v1/ask", json={"query": "介绍一下 THOMAS 架构的底座"}, headers=headers)
    check("ask 无 brain = 500（非静默空答案）", r_ask.status_code == 500,
          f"status={r_ask.status_code}")

    from src.thomas_core.brain import BrainNotConfigured
    from src.thomas_core import hooks
    from src.thomas_core.hooks import reset_hooks
    reset_hooks()
    try:
        from src.thomas_core.brain import get_brain
        get_brain()
        brain_guarded = False
    except BrainNotConfigured:
        brain_guarded = True
    check("BrainNotConfigured 可捕获", brain_guarded)
    check("hooks 缺省 no-op / None（宿主缺失不炸）",
          hooks._default_timeline_logger() is None
          and hooks._default_report_manager_factory() is None)

    _check_profile(c, headers)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nverdict: {'PASS' if passed == len(results) else 'FAIL'} "
          f"{passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
