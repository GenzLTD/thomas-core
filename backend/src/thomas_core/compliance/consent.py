"""
Compliance Gate: Consent verification.
PIPL 合规：单独同意 / 目的限定 / 可撤回

三层产品授权（求职主路径）：
  1. jobseeker_core  — 简历处理 + 职位匹配 + 保存报告
  2. credit_query    — 企业征信 / 工商风险查询（含文本分析）
  3. report_share    — 匹配报告对外分享

其余 scope 保留为「其他能力」细粒度授权。
"""
from __future__ import annotations

import functools
import logging
import uuid
from datetime import datetime
from typing import Callable

from flask import g, current_app, request, jsonify

logger = logging.getLogger("looma.compliance.consent")

ALL_SCOPES = frozenset({
    # Tier packages / primary
    "jobseeker_core",
    "credit_query",
    "report_share",
    # Covered by jobseeker_core (legacy fine-grained, still accepted)
    "resume_upload",
    "resume_parse",
    "job_match",
    "report_generate",
    "application_submit",
    # Covered by credit_query
    "credit_analyze",
    # Other product capabilities
    "profile_share",
    "ask_rag",
    "mbti_analyze",
    "navigator_memory",
})

# Package scope → child scopes granted/checked together
CONSENT_PACKAGES: dict[str, frozenset[str]] = {
    "jobseeker_core": frozenset({
        "resume_upload",
        "resume_parse",
        "job_match",
        "report_generate",
        "application_submit",
    }),
    "credit_query": frozenset({
        "credit_analyze",
    }),
}

# Child → parent package (for check() aliasing)
_CHILD_TO_PACKAGE: dict[str, str] = {
    child: pkg
    for pkg, children in CONSENT_PACKAGES.items()
    for child in children
}

# Frontend / docs: which scopes are the three product tiers
PRIMARY_TIERS = ("jobseeker_core", "credit_query", "report_share")

SCOPE_LABELS_ZH = {
    "jobseeker_core": "求职核心处理",
    "credit_query": "企业风险查询",
    "report_share": "匹配报告对外分享",
    "resume_upload": "上传简历文件",
    "resume_parse": "简历结构化提取",
    "job_match": "职位智能匹配",
    "report_generate": "生成并保存匹配报告",
    "application_submit": "投递简历到职位",
    "credit_analyze": "征信文本分析",
    "profile_share": "分享人格分析结果",
    "ask_rag": "AI 知识库问答",
    "mbti_analyze": "MBTI 性格测评",
    "navigator_memory": "对话记忆持久化",
}


def _now_iso():
    return datetime.now().isoformat()


class ConsentManager:
    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is not None:
            return self._db
        return getattr(current_app, "_db", None) or getattr(g, "_db", None)

    def _has_granted(self, conn, user_id: str, scope: str) -> bool:
        row = conn.execute(
            "SELECT id FROM consents WHERE user_id=? AND scope=? AND status='granted'",
            (user_id, scope),
        ).fetchone()
        return row is not None

    def grant(self, user_id, scope, ip="", user_agent="", purpose=""):
        if scope not in ALL_SCOPES:
            raise ValueError(f"Unknown consent scope: {scope}")
        # Grant package + all children in one batch
        targets = [scope]
        if scope in CONSENT_PACKAGES:
            targets.extend(sorted(CONSENT_PACKAGES[scope]))

        results = []
        primary = None
        for s in targets:
            r = self._grant_one(user_id, s, ip=ip, user_agent=user_agent, purpose=purpose or s)
            results.append({"scope": s, **r})
            if s == scope:
                primary = r
        out = dict(primary or results[0])
        if len(results) > 1:
            out["expanded"] = results
        return out

    def _grant_one(self, user_id, scope, ip="", user_agent="", purpose=""):
        cid = str(uuid.uuid4())
        now = _now_iso()
        db = self.db
        if db is None:
            raise RuntimeError("No database available")
        with db.get_conn() as conn:
            ex = conn.execute(
                "SELECT id FROM consents WHERE user_id=? AND scope=? AND status='granted'",
                (user_id, scope),
            ).fetchone()
            if ex:
                return {"consent_id": ex["id"], "already_granted": True}
            conn.execute(
                """INSERT INTO consents
                   (id, user_id, scope, purpose, status, ip, user_agent,
                    granted_at, created_at, updated_at)
                   VALUES (?,?,?,?,'granted',?,?,?,?,?)""",
                (cid, user_id, scope, purpose or scope, ip, user_agent, now, now, now),
            )
        return {"consent_id": cid, "already_granted": False}

    def revoke(self, user_id, scope):
        if scope not in ALL_SCOPES:
            return {"revoked": False, "reason": "Unknown scope"}
        targets = [scope]
        if scope in CONSENT_PACKAGES:
            targets.extend(sorted(CONSENT_PACKAGES[scope]))
        # Revoking a child also drops the parent package (package no longer intact)
        parent = _CHILD_TO_PACKAGE.get(scope)
        if parent and parent not in targets:
            targets.append(parent)

        revoked_ids = []
        for s in targets:
            r = self._revoke_one(user_id, s)
            if r.get("revoked"):
                revoked_ids.append(r.get("consent_id"))
        if not revoked_ids:
            return {"revoked": False, "reason": "No active consent found"}
        return {"revoked": True, "consent_id": revoked_ids[0], "revoked_scopes": targets}

    def _revoke_one(self, user_id, scope):
        db = self.db
        if db is None:
            raise RuntimeError("No database available")
        now = _now_iso()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM consents WHERE user_id=? AND scope=? AND status='granted'",
                (user_id, scope),
            ).fetchone()
            if not row:
                return {"revoked": False, "reason": "No active consent found"}
            # Delete old revoked records to avoid UNIQUE(user_id, scope, status) violation
            conn.execute(
                "DELETE FROM consents WHERE user_id=? AND scope=? AND status='revoked'",
                (user_id, scope),
            )
            conn.execute(
                "UPDATE consents SET status='revoked', revoked_at=?, updated_at=? WHERE id=?",
                (now, now, row["id"]),
            )
        return {"revoked": True, "consent_id": row["id"]}

    def check(self, user_id, scope):
        """True if scope granted, or its parent package is granted.

        Also: if all children of a package were granted historically (without
        package row), treat package check as satisfied.
        """
        if scope not in ALL_SCOPES:
            return False
        db = self.db
        if db is None:
            return False
        with db.get_conn() as conn:
            if self._has_granted(conn, user_id, scope):
                return True
            # Child covered by package
            parent = _CHILD_TO_PACKAGE.get(scope)
            if parent and self._has_granted(conn, user_id, parent):
                return True
            # Package satisfied by all legacy children
            if scope in CONSENT_PACKAGES:
                children = CONSENT_PACKAGES[scope]
                if children and all(self._has_granted(conn, user_id, c) for c in children):
                    return True
        return False

    def get_user_consents(self, user_id):
        db = self.db
        if db is None:
            return []
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, scope, purpose, status, granted_at, revoked_at "
                "FROM consents WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def status_map(self, user_id) -> dict[str, bool]:
        """Effective status for every scope (includes package aliasing)."""
        return {s: self.check(user_id, s) for s in sorted(ALL_SCOPES)}

    def grant_batch(self, user_id, scopes, ip="", user_agent=""):
        results = []
        for scope in scopes:
            try:
                r = self.grant(user_id, scope, ip=ip, user_agent=user_agent)
                results.append({"scope": scope, **r})
            except Exception as e:
                results.append({"scope": scope, "error": str(e)})
        return {"granted": len([r for r in results if "error" not in r]), "results": results}

    def has_any(self, user_id, scopes):
        return any(self.check(user_id, s) for s in scopes)

    def has_all(self, user_id, scopes):
        return all(self.check(user_id, s) for s in scopes)


_cm = None

def get_consent_manager(db=None):
    global _cm
    if _cm is None:
        _cm = ConsentManager(db=db)
    elif db is not None and _cm._db is None:
        _cm._db = db
    return _cm

def reset_consent_manager():
    global _cm
    _cm = None

def require_consent(scope, extract_user_id=None):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = None
            if extract_user_id:
                uid = extract_user_id()
            else:
                uid = kwargs.get("user_id") or getattr(g, "user_id", None)
            # Ask client to grant the package when a child is required
            required_for_client = _CHILD_TO_PACKAGE.get(scope, scope)
            if not uid:
                return jsonify(
                    error="consent_required",
                    message=f"需要授权: {SCOPE_LABELS_ZH.get(required_for_client, required_for_client)}",
                    required_scope=required_for_client,
                ), 403
            c = get_consent_manager()
            if not c.check(uid, scope):
                return jsonify(
                    error="consent_required",
                    message=f"需要授权: {SCOPE_LABELS_ZH.get(required_for_client, required_for_client)}",
                    required_scope=required_for_client,
                    action="grant_consent",
                ), 403
            g.compliance_scope = scope
            g.compliance_user_id = uid
            return fn(*args, **kwargs)
        return wrapper
    return decorator
