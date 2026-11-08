"""邀请生命周期，只做 not_required。

issuer 与 redeemer 都来自已验证会话。调用方不能指定签发人。
设备策略若不是 not_required，准备和兑换都直接拒绝，不降级，也不发挑战。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

TERMINAL_TENANT = "genzer.terminal"
TERMINAL_AUDIENCE = "genzer.terminal.registration"
TERMINAL_PURPOSE = "account_registration"
_DEFAULT_TTL = timedelta(hours=24)
_MODES = ("not_required", "registered_credential_required")


class InvitationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def issue(db, issuer_sub: str, body: dict) -> dict:
    body = _object(body)
    now = _now()
    tenant, audience, purpose = _scope(body)
    key = _idempotency_key(body)
    recipient = _recipient(body)
    expires_at = _expires(body, now)
    max_redemptions = _max_redemptions(body)
    extensions = _extensions(body.get("extensions"))

    conn = db.open_immediate()
    try:
        policy = db.get_audience_policy(conn, tenant, audience, purpose)
        if not policy or not policy["issue_allowed"]:
            raise InvitationError(403, "policy_denied", "policy does not allow this audience")
        mode = policy["device_policy"]
        if mode not in _MODES:
            raise InvitationError(403, "policy_denied", "device policy is not available")

        existing = db.find_invitation_by_idempotency(conn, key)
        if existing:
            if existing["issuer_sub"] != issuer_sub:
                raise InvitationError(409, "idempotency_conflict", "idempotency key belongs to another principal")
            http = _issued(existing, duplicate=True)
            audit = _audit_meta(existing)
            invitation_id = existing["id"]
        else:
            invitation_id = str(uuid.uuid4())
            db.insert_invitation(conn, {
                "id": invitation_id,
                "tenant": tenant,
                "audience": audience,
                "purpose": purpose,
                "issuer_sub": issuer_sub,
                "recipient_sub": recipient,
                "max_redemptions": max_redemptions,
                "device_policy": mode,
                "extensions_json": extensions,
                "idempotency_key": key,
                "issued_at": _stamp(now),
                "expires_at": expires_at,
            })
            stored = db.find_invitation(conn, invitation_id)
            http = _issued(stored, duplicate=False)
            audit = _audit_meta(stored)
        db.finish_immediate(conn, commit=True)
    except Exception:
        db.finish_immediate(conn, commit=False)
        raise
    return {"http": http, "audit": audit, "invitation_id": invitation_id}


def inspect(db, invitation_id: str) -> dict:
    conn = db.open_immediate()
    try:
        row = db.find_invitation(conn, invitation_id)
        if not row:
            raise InvitationError(404, "not_found", "invitation not found")
        http = {
            "invitation": _invitation_body(row, include_issuer=False),
            "recipient_restricted": bool(row["recipient_sub"]),
        }
        audit = _audit_meta(row)
        db.finish_immediate(conn, commit=True)
    except Exception:
        db.finish_immediate(conn, commit=False)
        raise
    return {"http": http, "audit": audit, "invitation_id": row["id"]}


def prepare(db, invitation_id: str) -> dict:
    conn = db.open_immediate()
    try:
        row = db.find_invitation(conn, invitation_id)
        if not row:
            raise InvitationError(404, "not_found", "invitation not found")
        _require_not_required(row)
        http = {
            "invitation_id": row["id"],
            "status": row["status"],
            "device_policy": {"mode": row["device_policy"]},
            "challenge": None,
            "consumes_invitation": False,
        }
        audit = _audit_meta(row)
        db.finish_immediate(conn, commit=True)
    except Exception:
        db.finish_immediate(conn, commit=False)
        raise
    return {"http": http, "audit": audit, "invitation_id": row["id"]}


def redeem(db, invitation_id: str, redeemer_sub: str, body: dict) -> dict:
    body = _object(body)
    key = _idempotency_key(body)
    now = _now()
    conn = db.open_immediate()
    committed = False
    try:
        prior = db.find_redemption_by_idempotency(conn, key)
        if prior:
            if prior["invitation_id"] != invitation_id:
                raise InvitationError(409, "idempotency_conflict", "idempotency key does not match this invitation")
            if prior["redeemer_sub"] != redeemer_sub:
                raise InvitationError(409, "idempotency_conflict", "idempotency key belongs to another principal")
            row = db.find_invitation(conn, invitation_id)
            result = _redeemed(prior, row, duplicate=True)
            db.finish_immediate(conn, commit=True)
            committed = True
            return result

        row = db.find_invitation(conn, invitation_id)
        if not row:
            raise InvitationError(404, "not_found", "invitation not found")
        _match_scope(body, row)
        if row["recipient_sub"] and row["recipient_sub"] != redeemer_sub:
            raise InvitationError(403, "recipient_mismatch", "recipient does not match")
        _require_not_required(row)

        if row["status"] == "revoked":
            raise InvitationError(409, "revoked", "invitation revoked")
        count = db.count_redemptions(conn, invitation_id)
        if row["status"] == "exhausted" or count >= row["max_redemptions"]:
            raise InvitationError(409, "exhausted", "invitation exhausted")
        if row["status"] == "expired" or _is_past(row["expires_at"], now):
            if row["status"] == "active":
                db.update_invitation_state(conn, invitation_id, status="expired", redemption_count=count)
                db.finish_immediate(conn, commit=True)
                committed = True
            raise InvitationError(410, "expired", "invitation expired")
        if row["status"] != "active":
            raise InvitationError(409, "conflict", "invitation is not active")
        if db.find_redemption_for_principal(conn, invitation_id, redeemer_sub):
            raise InvitationError(409, "exhausted", "invitation exhausted")

        redeemed_at = _stamp(now)
        redemption_id = str(uuid.uuid4())
        verification = json.dumps({"required": False, "verified": False})
        db.insert_redemption(conn, {
            "id": redemption_id,
            "invitation_id": invitation_id,
            "audience": row["audience"],
            "purpose": row["purpose"],
            "redeemer_sub": redeemer_sub,
            "device_verification_json": verification,
            "idempotency_key": key,
            "redeemed_at": redeemed_at,
        })
        new_count = count + 1
        new_status = "exhausted" if new_count >= row["max_redemptions"] else "active"
        db.update_invitation_state(
            conn, invitation_id, status=new_status, redemption_count=new_count,
        )
        stored = db.find_redemption_by_idempotency(conn, key)
        current = db.find_invitation(conn, invitation_id)
        result = _redeemed(stored, current, duplicate=False)
        db.finish_immediate(conn, commit=True)
        committed = True
        return result
    except Exception:
        if not committed:
            db.finish_immediate(conn, commit=False)
        raise


def revoke(db, invitation_id: str, actor_sub: str) -> dict:
    conn = db.open_immediate()
    try:
        row = db.find_invitation(conn, invitation_id)
        if not row:
            raise InvitationError(404, "not_found", "invitation not found")
        if row["issuer_sub"] != actor_sub:
            raise InvitationError(403, "forbidden", "only the issuer can revoke")
        if row["status"] == "revoked":
            http = _revoked(row)
        else:
            count = db.count_redemptions(conn, invitation_id)
            if row["status"] != "active" or count > 0:
                raise InvitationError(409, "conflict", "invitation can no longer be revoked")
            db.update_invitation_state(conn, invitation_id, status="revoked", redemption_count=0)
            http = _revoked(db.find_invitation(conn, invitation_id))
        audit = _audit_meta(db.find_invitation(conn, invitation_id))
        db.finish_immediate(conn, commit=True)
    except Exception:
        db.finish_immediate(conn, commit=False)
        raise
    return {"http": http, "audit": audit, "invitation_id": invitation_id}


def _issued(row: dict, *, duplicate: bool) -> dict:
    return {
        "invitation": _invitation_body(row, include_issuer=True),
        "recipient_restricted": bool(row["recipient_sub"]),
        "duplicate": duplicate,
    }


def _invitation_body(row: dict, *, include_issuer: bool) -> dict:
    body = {
        "id": row["id"],
        "audience": row["audience"],
        "purpose": row["purpose"],
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "max_redemptions": row["max_redemptions"],
        "redemption_count": row["redemption_count"],
        "device_policy": {"mode": row["device_policy"]},
        "extensions": json.loads(row["extensions_json"] or "{}"),
    }
    if include_issuer:
        body["issuer"] = {"sub": row["issuer_sub"]}
    return body


def _redeemed(redemption: dict, invitation: dict, *, duplicate: bool) -> dict:
    verification = json.loads(redemption["device_verification_json"] or "{}")
    return {
        "http": {
            "redemption": {
                "invitation_id": redemption["invitation_id"],
                "audience": redemption["audience"],
                "purpose": redemption["purpose"],
                "redeemer": {"sub": redemption["redeemer_sub"]},
                "redeemed_at": redemption["redeemed_at"],
                "device_verification": {
                    "required": bool(verification.get("required")),
                    "verified": bool(verification.get("verified")),
                },
                "idempotency_key": redemption["idempotency_key"],
            },
            "duplicate": duplicate,
            "redemption_count": invitation["redemption_count"],
        },
        "audit": _audit_meta(invitation),
        "invitation_id": invitation["id"],
    }


def _revoked(row: dict) -> dict:
    return {
        "invitation_id": row["id"],
        "status": row["status"],
        "audience": row["audience"],
        "purpose": row["purpose"],
        "device_policy": {"mode": row["device_policy"]},
    }


def _audit_meta(row: dict) -> dict:
    return {
        "tenant": row["tenant"],
        "audience": row["audience"],
        "purpose": row["purpose"],
        "device_policy": row["device_policy"],
    }


def _require_not_required(row: dict) -> None:
    if row["device_policy"] != "not_required":
        raise InvitationError(409, "device_policy_unsupported", "device policy is not available")


def _match_scope(body: dict, row: dict) -> None:
    audience = (body.get("audience") or "").strip()
    purpose = (body.get("purpose") or "").strip()
    if not audience and not purpose:
        return
    if not audience or not purpose:
        raise InvitationError(422, "scope_mismatch", "audience and purpose do not match")
    if audience != row["audience"] or purpose != row["purpose"]:
        raise InvitationError(422, "scope_mismatch", "audience and purpose do not match")


def _object(body) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise InvitationError(422, "invalid_body", "JSON object required")
    return body


def _scope(body: dict) -> tuple[str, str, str]:
    tenant = (body.get("tenant") or "").strip() if isinstance(body.get("tenant"), str) else ""
    audience = (body.get("audience") or "").strip() if isinstance(body.get("audience"), str) else ""
    purpose = (body.get("purpose") or "").strip() if isinstance(body.get("purpose"), str) else ""
    if not tenant and not audience and not purpose:
        return TERMINAL_TENANT, TERMINAL_AUDIENCE, TERMINAL_PURPOSE
    if not tenant or not audience or not purpose:
        raise InvitationError(422, "invalid_scope", "tenant, audience, and purpose must be sent together")
    return tenant, audience, purpose


def _idempotency_key(body: dict) -> str:
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        raise InvitationError(422, "invalid_idempotency_key", "idempotency_key is required")
    key = key.strip()
    if len(key) > 200:
        raise InvitationError(422, "invalid_idempotency_key", "idempotency_key is too long")
    return key


def _recipient(body: dict) -> str | None:
    if "recipient_sub" not in body or body.get("recipient_sub") in (None, ""):
        return None
    value = body.get("recipient_sub")
    if not isinstance(value, str) or not value.strip():
        raise InvitationError(422, "invalid_recipient", "recipient_sub must be a principal")
    return value.strip()


def _max_redemptions(body: dict) -> int:
    value = body.get("max_redemptions", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvitationError(422, "invalid_max_redemptions", "max_redemptions must be an integer >= 1")
    return value


def _expires(body: dict, now: datetime) -> str:
    raw = body.get("expires_at")
    if raw in (None, ""):
        return _stamp(now + _DEFAULT_TTL)
    if not isinstance(raw, str):
        raise InvitationError(422, "invalid_expiry", "expires_at must be a date-time")
    try:
        when = _parse(raw)
    except ValueError:
        raise InvitationError(422, "invalid_expiry", "expires_at must be a date-time") from None
    if when <= now:
        raise InvitationError(422, "invalid_expiry", "expires_at must be in the future")
    return _stamp(when)


def _extensions(value) -> str:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise InvitationError(422, "invalid_extensions", "extensions must be an object")
    if _has_email_key(value):
        raise InvitationError(422, "invalid_extensions", "extensions must not carry an email")
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(raw) > 4096:
        raise InvitationError(422, "invalid_extensions", "extensions are too large")
    return raw


def _has_email_key(value) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() == "email" or _has_email_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_email_key(item) for item in value)
    return False


def _is_past(value: str, now: datetime) -> bool:
    try:
        return _parse(value) <= now
    except ValueError:
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
