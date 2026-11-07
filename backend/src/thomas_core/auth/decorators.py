"""
Authentication decorators for route protection.
Replaces the old AUTH_STUB with real JWT verification.

Dual-token support (RFC docs/rfc/supabase-unified-auth-v1.md D6):
  - looma JWT (iss=looma, HS256) —— 存量 token，过渡期继续接受
  - Supabase JWT (JWKS/ES256 或 custom HS256) —— 新统一认证源
"""
from functools import wraps
from flask import request, jsonify, g, current_app
from src.thomas_core.auth.jwt_handler import resolve_auth_token


def _resolve_user(db, source: str, payload: dict):
    """Resolve a looma user row from an authenticated token payload.

    source='looma':   payload['sub'] is a looma user id.
    source='supabase': payload['sub'] is a Supabase auth user UUID —
                       mapped via users.supabase_uid, auto-created/bound on
                       first sight (email matching covers legacy users).
    Returns user dict or None.
    """
    if source == "supabase":
        supabase_uid = payload.get("sub", "")
        user = db.get_user_by_supabase_uid(supabase_uid) if supabase_uid else None
        if user:
            return user
        # First contact: create local user or bind to a legacy email account
        email = payload.get("email") or ""
        name = (payload.get("user_metadata") or {}).get("full_name") or ""
        try:
            user, _ = db.get_or_create_user_by_supabase(
                supabase_uid, email=email, name=name
            )
        except Exception as e:  # keep auth non-fatal on mapping edge cases
            current_app.logger.warning(f"[auth] supabase user mapping failed: {e}")
            return None
        return user
    return db.get_user_by_id(payload.get("sub", ""))


def require_auth(f):
    """
    Require a valid looma or Supabase JWT in the Authorization header.
    Verifies token, loads user from DB, sets g.user_id / g.user_tier / g.user_role.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(error="unauthorized", message="Missing or invalid Authorization header"), 401

        token = auth_header[7:]  # strip "Bearer "
        try:
            source, payload = resolve_auth_token(token)
        except Exception as e:
            return jsonify(error="unauthorized", message=f"Invalid token: {str(e)}"), 401

        db = getattr(current_app, "_db", None)
        if db is None:
            return jsonify(error="server_error", message="database unavailable"), 500

        user = _resolve_user(db, source, payload)
        if not user:
            return jsonify(error="unauthorized", message="user not found"), 401

        g.user_id = user["id"]
        g.user_tier = user.get("tier", "free")
        g.user_role = user.get("role", "user")
        g.auth_source = source
        return f(*args, **kwargs)

    return decorated


def require_tier(min_tier: str):
    """
    Require the user to have at least the given tier.
    Tier hierarchy: guest < free < supporter < pro < enterprise
    Usage: @require_auth @require_tier("pro")
    """
    tier_order = {"guest": -1, "free": 0, "supporter": 1, "pro": 2, "enterprise": 3}

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_tier = g.get("user_tier", "free")
            if tier_order.get(user_tier, 0) < tier_order.get(min_tier, 0):
                return jsonify(
                    error="forbidden",
                    message=f"Requires tier '{min_tier}' or above"
                ), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_driver(f):
    """
    Require the authenticated user to hold a driver (or admin) role.
    On success sets g.driver_id = g.user_id —— 多租户归属过滤的锚点：
    后续所有 columns/articles 读写都必须以 g.driver_id 作用域执行，
    路由层不允许出现"无归属"的查询。

    Usage: @require_auth @require_driver
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        role = g.get("user_role", "user")
        if role not in ("driver", "admin"):
            return jsonify(
                error="forbidden",
                message="Driver role required for content management",
            ), 403
        g.driver_id = g.user_id
        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """
    Optional auth — if token is present, set g.user_id/g.user_tier;
    if absent, treat as guest with a random ID.
    Used by /v1/ask where guest users also have limited quota.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                source, payload = resolve_auth_token(token)
            except Exception:
                pass  # Invalid token → fall through to guest
            else:
                db = getattr(current_app, "_db", None)
                if db is not None:
                    user = _resolve_user(db, source, payload)
                    if user:
                        g.user_id = user["id"]
                        g.user_tier = user.get("tier", "free")
                        return f(*args, **kwargs)
                g.user_id = payload["sub"]
                g.user_tier = "free"
                return f(*args, **kwargs)

        import uuid
        g.user_id = f"guest-{str(uuid.uuid4())[:12]}"
        g.user_tier = "guest"
        return f(*args, **kwargs)

    return decorated
