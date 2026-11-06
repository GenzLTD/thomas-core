"""认钱认人：GFCC principal.sub ↔ looma users.id 最小 join。

设计（looma 运行时一本账）：
- users.principal_sub 存规范主体。ethos 未另行签发前，bootstrap 为
  principal_sub := users.id（文档等价；日后可换成真实 GFCC sub）。
- 外部身份沿用 user_identities(provider, provider_uid)，语义对齐
  invitation.v1 的 (issuer, subject)（issuer=provider，subject=provider_uid）。
  微信另认 users.wechat_openid。
- 结算只认 resolve_settlement_user_id 算出的唯一 users.id；
  会话与外部主体冲突时抛 AmbiguousLedgerSubject。

GFCC 1.6.0 只定义协议语言；本模块是交付层接线，不修改 gfcc JSON。
"""

from __future__ import annotations

from typing import Any, Optional


class AmbiguousLedgerSubject(ValueError):
    """无法唯一解析到账本用户（冲突或缺失）。"""


def ensure_principal_sub(db: Any, user_id: str) -> str:
    """保证用户有 principal_sub；缺失则 bootstrap 为 users.id。"""
    if not user_id:
        raise AmbiguousLedgerSubject("missing user_id")
    user = db.get_user_by_id(user_id)
    if not user:
        raise AmbiguousLedgerSubject(f"unknown user_id={user_id}")
    existing = (user.get("principal_sub") or "").strip()
    if existing:
        return existing
    db.set_principal_sub(user_id, user_id)
    return user_id


def _user_id_for_external(db: Any, issuer: str, subject: str) -> Optional[str]:
    issuer = (issuer or "").strip()
    subject = (subject or "").strip()
    if not issuer or not subject:
        return None
    linked = db.get_user_by_identity(issuer, subject)
    if linked:
        return linked["id"]
    if issuer in ("wechat", "wechat_openid"):
        by_openid = db.get_user_by_openid(subject)
        if by_openid:
            return by_openid["id"]
    return None


def resolve_settlement_user_id(
    db: Any,
    *,
    session_user_id: Optional[str] = None,
    order_user_id: Optional[str] = None,
    issuer: Optional[str] = None,
    subject: Optional[str] = None,
) -> str:
    """解析唯一结算主体并确保 principal_sub。"""
    candidates: set[str] = set()
    if order_user_id:
        candidates.add(order_user_id)
    if session_user_id:
        candidates.add(session_user_id)
    if issuer and subject:
        ext = _user_id_for_external(db, issuer, subject)
        if ext:
            candidates.add(ext)
        elif not candidates:
            raise AmbiguousLedgerSubject(
                f"external subject not linked: {issuer}:{subject}"
            )

    if not candidates:
        raise AmbiguousLedgerSubject("no settlement subject")
    if len(candidates) > 1:
        raise AmbiguousLedgerSubject(
            "conflicting settlement subjects: " + ",".join(sorted(candidates))
        )
    uid = next(iter(candidates))
    ensure_principal_sub(db, uid)
    return uid
