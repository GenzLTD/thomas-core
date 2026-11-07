"""
Quota management — tier-based daily limits with boost pack fallback.

Migrated from old quota.py, adapted for Flask + new DBManager.
Strategy: user usage = training data, free tier generous, paid tier unrestricted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from flask import current_app, g

# Resource names
RESOURCE_JOB_MATCH = "job_match"
RESOURCE_ASK = "ask"
RESOURCE_RESUME_PARSE = "resume_parse"
RESOURCE_RAG = "rag"

# Tier-based daily limits (99999 = effectively unlimited)
QUOTA_LIMITS = {
    "guest": {
        RESOURCE_JOB_MATCH: 1,
        RESOURCE_ASK: 3,
        RESOURCE_RESUME_PARSE: 1,
        RESOURCE_RAG: 2,
    },
    "free": {
        RESOURCE_JOB_MATCH: 5,
        RESOURCE_ASK: 30,
        RESOURCE_RESUME_PARSE: 3,
        RESOURCE_RAG: 10,
    },
    "supporter": {
        RESOURCE_JOB_MATCH: 99999,
        RESOURCE_ASK: 99999,
        RESOURCE_RESUME_PARSE: 99999,
        RESOURCE_RAG: 99999,
    },
    "pro": {
        RESOURCE_JOB_MATCH: 99999,
        RESOURCE_ASK: 99999,
        RESOURCE_RESUME_PARSE: 99999,
        RESOURCE_RAG: 99999,
    },
    "enterprise": {
        RESOURCE_JOB_MATCH: 99999,
        RESOURCE_ASK: 99999,
        RESOURCE_RESUME_PARSE: 99999,
        RESOURCE_RAG: 99999,
    },
}

# Upgrade hints
UPGRADE_HINT_GUEST_EXHAUSTED = {
    "reason": "guest_quota_exhausted",
    "message": "今日免费体验次数已用完（3次）。注册账号解锁每日30次AI诗词问答，还有诗词搜索、诗人分析等更多功能！",
    "register_url": "/v1/auth/register",
    "upgrade_tiers": [
        {"tier": "free", "name": "免费版", "daily_quota": 30, "price_monthly": "免费",
         "features": ["每日10次诗词搜索", "每日30次AI诗词问答", "基础诗人浏览", "诗词收藏"]},
        {"tier": "supporter", "name": "支持者版", "daily_quota": 99999, "price_monthly": "¥29/月",
         "features": ["无限诗词搜索", "AI 诗词问答", "深度诗人分析", "去广告"]},
    ],
}

UPGRADE_HINT_FREE_EXHAUSTED = {
    "reason": "free_quota_exhausted",
    "message": "今日免费版配额已用尽。免费版每日30次AI诗词问答、10次诗词搜索。如需无限使用，29元/月解锁支持者版。",
    "register_url": None,
    "upgrade_tiers": [
        {"tier": "supporter", "name": "支持者版 · 去限制", "daily_quota": 99999, "price_monthly": "¥29/月",
         "features": ["无限诗词搜索", "AI 诗词问答", "深度诗人分析", "去广告"]},
        {"tier": "enterprise", "name": "企业版", "daily_quota": 99999, "price_monthly": "联系销售",
         "features": ["企业级 RAG 知识库", "私有云部署", "数据隔离", "专属支持"]},
    ],
}

UPGRADE_HINT_SCOPE_FORBIDDEN = {
    "reason": "scope_forbidden",
    "message": "当前免费版仅支持公开诗词知识库查询。升级支持者版可解锁深度诗人分析与企业级 RAG 检索。",
    "register_url": None,
    "upgrade_tiers": [
        {"tier": "supporter", "name": "支持者版", "daily_quota": 99999, "price_monthly": "¥29/月",
         "features": ["深度诗人分析", "企业级 RAG 知识库", "无限诗词搜索"]},
    ],
}

# In-memory fallback (when DB is unavailable)
_memory: dict[str, int] = {}
_lock = Lock()


def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _storage_key(user_id: str, resource: str) -> str:
    return f"quota:{user_id}:{resource}:{_today_key()}"


def build_upgrade_hint(tier: str, used: int, reason: str = "quota_exhausted") -> dict:
    """Build upgrade hint based on tier and reason."""
    if reason == "scope_forbidden":
        hint = dict(UPGRADE_HINT_SCOPE_FORBIDDEN)
    elif tier == "guest":
        hint = dict(UPGRADE_HINT_GUEST_EXHAUSTED)
    else:
        hint = dict(UPGRADE_HINT_FREE_EXHAUSTED)

    hint["daily_limit"] = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["guest"]).get(RESOURCE_ASK, 0)
    hint["used"] = used
    return hint


def get_remaining(user_id: str, tier: str, resource: str) -> int:
    """Get remaining quota for user + tier + resource."""
    limit = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["guest"]).get(resource, 0)
    date = _today_key()

    try:
        db = current_app._db
        record = db.get_quota(user_id, resource, date)
        if record:
            return max(0, limit - record["used"])
        return limit
    except Exception:
        pass

    key = _storage_key(user_id, resource)
    with _lock:
        used = _memory.get(key, 0)
    return max(0, limit - used)


def consume(user_id: str, tier: str, resource: str) -> bool:
    """Consume 1 quota unit. Returns True=success, False=exceeded."""
    limit = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["guest"]).get(resource, 0)
    date = _today_key()

    try:
        db = current_app._db
        return db.consume_quota(user_id, resource, date, limit)
    except Exception:
        pass

    key = _storage_key(user_id, resource)
    with _lock:
        used = _memory.get(key, 0)
        if used >= limit:
            return False
        _memory[key] = used + 1
    return True


def consume_with_boost(user_id: str, tier: str, resource: str) -> dict:
    """Consume quota with boost pack fallback. Priority: daily quota -> boost credits."""
    limit = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["guest"]).get(resource, 0)
    date = _today_key()

    try:
        db = current_app._db
        boost_remaining = db.get_boost_credit_remaining(user_id)

        if db.consume_quota(user_id, resource, date, limit):
            record = db.get_quota(user_id, resource, date)
            daily_used = record["used"] if record else 1
            return {
                "ok": True, "source": "daily",
                "daily_remaining": max(0, limit - daily_used),
                "boost_remaining": boost_remaining,
            }

        if boost_remaining > 0 and db.consume_boost_credit(user_id, resource):
            boost_remaining = db.get_boost_credit_remaining(user_id)
            return {
                "ok": True, "source": "boost",
                "daily_remaining": 0,
                "boost_remaining": boost_remaining,
            }

        return {"ok": False, "source": "none", "daily_remaining": 0, "boost_remaining": boost_remaining}
    except Exception:
        pass

    ok = consume(user_id, tier, resource)
    return {"ok": ok, "source": "daily" if ok else "none", "daily_remaining": -1, "boost_remaining": -1}


def refund_consumption(user_id: str, resource: str, source: str = "daily") -> bool:
    """Best-effort refund after a failed request that already consumed quota."""
    if source != "daily":
        # Boost credits are not auto-refunded in v1.
        return False
    date = _today_key()
    try:
        db = current_app._db
        return db.refund_quota(user_id, resource, date)
    except Exception:
        pass
    key = _storage_key(user_id, resource)
    with _lock:
        used = _memory.get(key, 0)
        if used <= 0:
            return False
        _memory[key] = used - 1
    return True


def get_boost_credit_remaining(user_id: str) -> int:
    """Get user's boost pack remaining credits."""
    try:
        db = current_app._db
        return db.get_boost_credit_remaining(user_id)
    except Exception:
        return 0


def check_quota() -> tuple:
    """Flask-compatible: check if current user has remaining quota.

    Returns: (allowed: bool, remaining: int, limit: int)
    """
    tier = g.get("user_tier", "free")
    if tier in ("supporter", "pro", "enterprise"):
        return (True, 999999, 999999)

    db = current_app._db
    used = db.get_daily_usage_count(g.user_id)
    limit = current_app.config["FREE_DAILY_LIMIT"]
    remaining = max(0, limit - used)
    return (remaining > 0, remaining, limit)


def consume_quota(endpoint: str, tokens_used: int = 0):
    """Flask-compatible: log a usage event for the current user."""
    db = current_app._db
    db.log_usage(g.user_id, endpoint, tokens_used)


# top_n limits per tier
TOP_N_LIMIT = {
    "guest": 3, "free": 5, "supporter": 10, "pro": 10, "enterprise": 20,
}


def clamp_top_n(tier: str, requested: int) -> int:
    """Clamp top_n by tier."""
    max_n = TOP_N_LIMIT.get(tier, TOP_N_LIMIT["guest"])
    return min(max(requested, 1), max_n)
