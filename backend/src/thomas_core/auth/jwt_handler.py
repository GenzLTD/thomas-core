"""
JWT token signing and verification.
Replaces the old AUTH_STUB mechanism with real JWT.

Supabase integration (RFC docs/rfc/supabase-unified-auth-v1.md):
  - Supabase Auth 签发的 token 用 JWKS (ES256) 验证
  - looma 为微信/华为代签的 custom token 用 SUPABASE_JWT_SECRET (HS256) 验证
  - 存量 looma token (iss=looma) 过渡期继续支持
"""
import jwt
import time
import uuid
from flask import current_app, g


def sign_token_for_user(db, user_id: str) -> str:
    """Issue a JWT from the current DB user record (tier/email synced)."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise ValueError("user not found")
    extra = {"tier": user.get("tier", "free")}
    email = user.get("email")
    if email:
        extra["email"] = email
    return sign_token(user_id, extra_claims=extra)


def sign_token(user_id: str, extra_claims: dict = None) -> str:
    """
    Sign a looma JWT for the given user_id.
    Returns a compact JWT string.
    """
    config = current_app.config
    now = int(time.time())
    payload = {
        "sub": user_id,           # subject = looma user_id
        "iat": now,               # issued at
        "exp": now + config["JWT_EXPIRY_HOURS"] * 3600,
        "iss": "looma",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, config["JWT_SECRET"], algorithm=config["JWT_ALGORITHM"])


def verify_token(token: str) -> dict:
    """
    Verify a looma JWT.
    Returns the decoded payload dict if valid.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    config = current_app.config
    return jwt.decode(
        token,
        config["JWT_SECRET"],
        algorithms=[config["JWT_ALGORITHM"]],
        issuer="looma",
    )


def get_current_user_id() -> str:
    """Get the authenticated user_id from request context (set by @require_auth)."""
    return g.get("user_id")


def get_current_user_tier() -> str:
    """Get the authenticated user's tier from request context."""
    return g.get("user_tier", "free")


# ============================================
# Supabase token verification / signing
# ============================================

def verify_supabase_token(token: str) -> dict:
    """Verify a Supabase-family JWT.

    Two accepted forms:
      1. Supabase Auth 签发的 token —— JWKS (ES256) 验证，aud=authenticated
      2. looma 代签的 custom token（微信/华为）—— HS256 + SUPABASE_JWT_SECRET 验证

    Returns the decoded payload dict.
    Raises jwt.InvalidTokenError on failure.
    """
    config = current_app.config
    errors = []

    # 1) Custom token: HS256 signed with SUPABASE_JWT_SECRET (no network)
    sb_secret = config.get("SUPABASE_JWT_SECRET", "") or ""
    if sb_secret:
        try:
            return jwt.decode(
                token,
                sb_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except Exception as e:
            errors.append(f"custom-hs256: {e}")

    # 2) Supabase Auth token: ES256 via JWKS (network fetch, cached)
    jwks_url = config.get("SUPABASE_JWKS_URL", "") or ""
    if not jwks_url:
        raise jwt.InvalidTokenError("supabase not configured")
    try:
        from jwt import PyJWKClient

        client = PyJWKClient(jwks_url, cache_keys=True, lifespan=600)
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience="authenticated",
        )
    except Exception as e:
        errors.append(f"jwks: {e}")

    raise jwt.InvalidTokenError("; ".join(errors) or "invalid supabase token")


def sign_supabase_custom_token(supabase_uid: str, email: str = "",
                               provider: str = "wechat",
                               user_metadata: dict = None) -> str:
    """Sign a custom Supabase access token (HS256 + SUPABASE_JWT_SECRET).

    用于无原生 Supabase provider 的登录路径（微信小程序 / 华为）。
    iss 必须指向 Supabase auth/v1 才能被 Supabase 网关接受。
    """
    config = current_app.config
    now = int(time.time())
    payload = {
        "iss": f"{config['SUPABASE_URL'].rstrip('/')}/auth/v1",
        "sub": supabase_uid,
        "aud": "authenticated",
        "iat": now,
        "exp": now + config["JWT_EXPIRY_HOURS"] * 3600,
        "email": email or "",
        "phone": "",
        "role": "authenticated",
        "aal": "aal1",
        "amr": [{"method": "oauth", "timestamp": now}],
        "session_id": str(uuid.uuid4()),
        "app_metadata": {"provider": provider, "providers": [provider]},
        "user_metadata": user_metadata or {},
    }
    return jwt.encode(payload, config["SUPABASE_JWT_SECRET"], algorithm="HS256")


def resolve_auth_token(token: str):
    """Return (source, payload) for a bearer token.

    source: 'looma'（存量 looma JWT）| 'supabase'（Supabase Auth / custom token）。
    Raises jwt.InvalidTokenError when the token is not valid under any scheme.
    """
    try:
        return "looma", verify_token(token)
    except Exception:
        pass
    try:
        return "supabase", verify_supabase_token(token)
    except Exception:
        pass
    raise jwt.InvalidTokenError("token failed looma and supabase verification")
