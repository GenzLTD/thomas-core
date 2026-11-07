"""R1 键位强制（Phase 1）：`X-User-Id` 必须等于 token 解出的 looma user id。

为什么做成共用模块：核进程（:5300）与 in-process 模式的宿主（:5200）跑的是同一批
路由，键位校验必须**同一份实现**，否则两种模式的安全边界不一致（自测里就是这样
暴露的：核进程 403、宿主 200）。

规则（刻意留兼容面）：
- 客户端**不主动带** `X-User-Id` → 放行（存量调用不受影响）；
- 带了但与 token 所属 user 不一致 → **403 `user_id_mismatch`**（负向断言用）；
- 只带 `X-User-Id` 不带 Bearer → 401 `unauthorized`；
- 登录 / 注册 / `/health` 不做校验（此时还没有身份）。
"""
from __future__ import annotations

from flask import current_app, jsonify, request

from src.thomas_core.auth.decorators import _resolve_user
from src.thomas_core.auth.jwt_handler import resolve_auth_token

SKIP_PREFIXES = ("/v1/auth/login", "/v1/auth/register")


def register_user_id_key_guard(app) -> None:
    @app.before_request
    def enforce_user_id_key():
        if request.method == "OPTIONS" or not request.path.startswith("/v1/"):
            return None
        if request.path.startswith(SKIP_PREFIXES):
            return None
        claimed = (request.headers.get("X-User-Id") or "").strip()
        if not claimed:
            return None
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return (
                jsonify(error="unauthorized", message="X-User-Id 必须与 Bearer token 同时提供"),
                401,
            )
        try:
            source, payload = resolve_auth_token(authorization[7:])
            user = _resolve_user(current_app._db, source, payload)
        except Exception:
            return jsonify(error="unauthorized", message="token 无法解析"), 401
        actual = None
        if user is not None:
            try:
                actual = user["id"]
            except Exception:
                actual = getattr(user, "id", None)
        if actual and actual != claimed:
            return (
                jsonify(error="user_id_mismatch", claimed=claimed, token_user_id=actual),
                403,
            )
        return None
