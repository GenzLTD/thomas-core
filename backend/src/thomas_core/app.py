"""THOMAS core standalone app（刀 4）。

create_core_app() 只装配核面：auth / ask / compliance 三蓝图 + /health，
与宿主 create_app()（:5200，27 蓝图）并存；同 Config、同 DB（同库不拆文件）。
R1：本 app 的写权只落在 core_schema 7 表。

health 判据（四机验收卡）：service="thomas-core" 且 deploy_track="looma"。
ask 热路径仍经 src.agents.central_brain（RFC 裁决 1 例外条款的暂行默认实现，
Phase 1 换 brain_bridge 宿主注入；本文件不改 ask_routes——行为不变纪律）。
"""
from __future__ import annotations

import os

from flask import Flask, jsonify
from flask_cors import CORS

from src.config import Config


def create_core_app(env: str = "development") -> Flask:
    """Build the core-only Flask app (:5300). Host app (:5200) untouched."""
    from src.app import _git_commit, _refresh_config

    app = Flask("thomas-core")
    _refresh_config()  # re-read env vars so per-test overrides are picked up
    app.config.from_object(Config)

    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=True)

    # --- Core blueprints only ---
    from src.thomas_core.routes.ask_routes import ask_bp
    from src.thomas_core.routes.auth_routes import auth_bp
    from src.thomas_core.routes.compliance_routes import compliance_bp

    app.register_blueprint(auth_bp, url_prefix="/v1/auth")
    app.register_blueprint(ask_bp, url_prefix="/v1")
    app.register_blueprint(compliance_bp, url_prefix="/v1/compliance")

    # --- Initialize database on first request (split 模式：core 只建 core schema) ---
    from src.db import schema_loader
    from src.db.manager import DatabaseManager

    @app.before_request
    def init_db():
        if not getattr(app, "_db_initialized", False):
            db_path = app.config["DATABASE_PATH"]
            split = schema_loader.split_enabled()
            if split:
                info = schema_loader.ensure_scope(db_path, "core")
                app.logger.info("[core] schema scope=core ensured: %s", info)
            db = DatabaseManager(db_path)
            if not split:
                db.init_schema()
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
        return jsonify(
            status="ok" if llm_ready else "degraded",
            service="thomas-core",
            version="core-v1",
            git_commit=_git_commit(),
            deploy_track="looma",
            llm_provider=primary_llm,
            llm_configured=llm_ready,
            core_blueprints=["auth", "ask", "compliance"],
        )

    return app
