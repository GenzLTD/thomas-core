"""
Supabase Auth integration — THOMAS 生态统一身份层 (RFC docs/rfc/supabase-unified-auth-v1.md).

职责：
  1. Admin API（service_role）upsert 微信/华为 Supabase 用户
  2. 通过占位邮箱 <openid>@<provider>.thomas.local 建立确定映射，避免遍历 user_metadata

依赖 config：SUPABASE_URL / SUPABASE_SECRET_KEY / SUPABASE_PUBLISHABLE_KEY。
未配置 SUPABASE_URL 时所有函数抛出 SupabaseUnconfiguredError，调用方回退旧路径。
"""
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)

# 占位邮箱后缀，避免与真实用户邮箱冲突（Supabase email 唯一约束）
PLACEHOLDER_DOMAIN = "thomas.local"


class SupabaseUnconfiguredError(RuntimeError):
    """Raised when SUPABASE_URL / SUPABASE_SECRET_KEY are not configured."""


def _auth_url(path: str = "") -> str:
    url = (current_app.config.get("SUPABASE_URL") or "").rstrip("/")
    if not url:
        raise SupabaseUnconfiguredError("SUPABASE_URL not configured")
    return f"{url}/auth/v1{path}"


def _admin_headers() -> dict:
    secret = current_app.config.get("SUPABASE_SECRET_KEY") or ""
    if not secret:
        raise SupabaseUnconfiguredError("SUPABASE_SECRET_KEY not configured")
    return {
        "apikey": secret,
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def placeholder_email(openid: str, provider: str) -> str:
    """占位邮箱：<openid>@<provider>.thomas.local"""
    return f"{openid}@{provider}.{PLACEHOLDER_DOMAIN}"


def admin_get_user_by_email(email: str):
    """Look up a Supabase auth user by email (exact match). Returns dict or None.

    NOTE: 实测该 GoTrue 实例的 `?email=` / `?search=` / `?filter=` 查询参数
    均不可靠（`email=` 忽略参数返回全部、`filter=` 返回空），
    曾导致微信 upsert 错误命中/创建失败。必须全量分页拉取后本地精确匹配。
    """
    if not email:
        return None
    email_l = email.strip().lower()
    headers = _admin_headers()
    page = 1
    per_page = 200
    while True:
        try:
            resp = requests.get(
                _auth_url("/admin/users"),
                headers=headers,
                params={"page": page, "per_page": per_page},
                timeout=15,
            )
        except requests.RequestException as e:
            logger.error(f"[supabase_admin] GET /admin/users failed: {e}")
            raise
        if resp.status_code != 200:
            logger.error(
                f"[supabase_admin] GET /admin/users status={resp.status_code}: {resp.text[:300]}"
            )
            return None
        users = resp.json().get("users", [])
        for u in users:
            if (u.get("email") or "").strip().lower() == email_l:
                return u
        if len(users) < per_page:
            break
        page += 1
    return None


def admin_create_user(openid: str, provider: str, full_name: str = "") -> dict:
    """Create a Supabase auth user for a provider-native identity (wechat/huawei)."""
    email = placeholder_email(openid, provider)
    payload = {
        "email": email,
        "email_confirm": True,
        "user_metadata": {
            "provider": provider,
            "wechat_openid": openid if provider == "wechat" else "",
            "huawei_openid": openid if provider == "huawei" else "",
            "full_name": full_name or "",
        },
        "app_metadata": {"provider": provider, "providers": [provider]},
    }
    try:
        resp = requests.post(
            _auth_url("/admin/users"),
            headers=_admin_headers(),
            json=payload,
            timeout=15,
        )
    except requests.RequestException as e:
        logger.error(f"[supabase_admin] POST /admin/users failed: {e}")
        raise
    if resp.status_code not in (200, 201):
        logger.error(
            f"[supabase_admin] POST /admin/users status={resp.status_code}: {resp.text[:300]}"
        )
        raise RuntimeError(f"Supabase admin create user failed: {resp.status_code}")
    return resp.json()


def upsert_supabase_user(openid: str, provider: str = "wechat",
                         full_name: str = "") -> dict:
    """Find-or-create a Supabase auth user by provider openid.

    Returns the Supabase auth user dict (has 'id' = supabase UUID).
    """
    email = placeholder_email(openid, provider)
    user = admin_get_user_by_email(email)
    if user:
        return user
    return admin_create_user(openid, provider, full_name)
