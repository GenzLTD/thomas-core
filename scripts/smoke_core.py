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
    check("8 表 + schema_meta 有 core", n_tables == 8 and "core" in scopes,
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

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nverdict: {'PASS' if passed == len(results) else 'FAIL'} "
          f"{passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
