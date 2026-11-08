"""THOMAS core standalone app（刀 4；刀 5 起完全自足）。

create_core_app() 只装配核面：auth / ask / compliance 三蓝图 + /health，
与宿主 create_app()（:5200，27 蓝图）并存；同库不同写权面。
R1：本 app 的写权只落在 core_schema 7 表（经 `CoreDB`，刀 5c）。

自足性（刀 5）：核不 import 任何宿主模块。ask 热路径上的三处产品依赖改走注入点 ——
`hooks.record_interaction_log`（时间线埋点）/ `hooks.report_manager`（匹配报告）/
`brain.get_brain()`（意图解析与派发，RFC 裁决 1）。宿主 `create_app()` 会注册实现；
宿主不在时按缺省语义降级（埋点 no-op、报告 None、brain 抛 BrainNotConfigured）。

health 判据（四机验收卡）：service="thomas-core" 且 deploy_track="looma"。
"""
from __future__ import annotations

import os

from flask import Flask, jsonify
from flask_cors import CORS

from src.thomas_core.config import CoreConfig
from src.thomas_core.runtime import git_commit


def create_core_app(env: str = "development") -> Flask:
    """Build the core-only Flask app (:5300). Host app (:5200) untouched."""
    app = Flask("thomas-core")
    CoreConfig.refresh()  # re-read env vars so per-test overrides are picked up
    app.config.from_object(CoreConfig)

    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=True)

    # --- Core blueprints only ---
    from src.thomas_core.routes.ask_routes import ask_bp
    from src.thomas_core.routes.auth_routes import auth_bp
    from src.thomas_core.routes.compliance_routes import compliance_bp
    from src.thomas_core.routes.game_routes import game_bp
    from src.thomas_core.routes.profile_routes import profile_bp

    app.register_blueprint(auth_bp, url_prefix="/v1/auth")
    app.register_blueprint(ask_bp, url_prefix="/v1")
    app.register_blueprint(compliance_bp, url_prefix="/v1/compliance")
    # 母舰答题。health 的 core_blueprints 仍只报 auth/ask/compliance，四机验收卡按这个三元组比对。
    app.register_blueprint(game_bp, url_prefix="/v1/game")
    app.register_blueprint(profile_bp, url_prefix="/v1/profile")

    # --- Initialize database on first request (核只碰 core 面：刀 5c 起用 CoreDB) ---
    from src.thomas_core.db.core_db import CoreDB

    @app.before_request
    def init_db():
        if not getattr(app, "_db_initialized", False):
            db_path = app.config["DATABASE_PATH"]
            db = CoreDB(db_path)
            # split=1：只建 core scope；split=0（legacy 回退）：core + product 两份 DDL 都建，
            # 等价于过去的全量建表（迁移块留在宿主 DatabaseManager.init_schema）。
            info = db.init_core_schema()
            app.logger.info("[core] schema ensured: %s", info)
            app._db = db
            app._db_initialized = True

    # --- R1 键位强制（Phase 1）：与 in-process 宿主共用同一份实现 ---
    # 规则见 src/thomas_core/keys.py：带错 → 403 user_id_mismatch；只带键位不带 token → 401；
    # 不带键位 → 放行（存量调用不受影响）。
    from src.thomas_core.keys import register_user_id_key_guard

    register_user_id_key_guard(app)

    # --- Health ---
    @app.route("/health", methods=["GET"])
    def health():
        llm_order_raw = (
            app.config.get("LLM_PROVIDER_ORDER")
            or os.getenv("LLM_PROVIDER_ORDER")
            or "deepseek"
        )
        primary_llm = str(llm_order_raw).split(",")[0].strip().lower() or "deepseek"
        has_deepseek = bool(
            (app.config.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip()
        )
        llm_ready = primary_llm == "ollama" or has_deepseek
        from src.thomas_core.profile.chroma_index import chroma_ready

        return jsonify(
            status="ok" if llm_ready else "degraded",
            service="thomas-core",
            version="core-v1",
            git_commit=git_commit(),
            deploy_track="looma",
            llm_provider=primary_llm,
            llm_configured=llm_ready,
            chroma_ok=chroma_ready(app.config["DATABASE_PATH"]),
            core_blueprints=["auth", "ask", "compliance"],
        )

    return app
