"""邀请五条路由。全部要 Bearer。不签会话，不读宿主租户表。"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from src.thomas_core.auth.decorators import require_auth
from src.thomas_core.compliance.audit import get_audit_logger
from src.thomas_core.identity.ledger_subject import ensure_principal_sub
from src.thomas_core.invitation import engine

invitation_bp = Blueprint("invitation", __name__)
credential_bp = Blueprint("device_credential", __name__)

_AUDIT_KEYS = ("tenant", "audience", "purpose", "device_policy")


def _principal() -> str:
    return ensure_principal_sub(current_app._db, g.user_id)


def _error(exc: engine.InvitationError):
    return jsonify(error=exc.code, message=exc.message), exc.status


def _audit(actor: str, action: str, result: dict) -> None:
    meta = {key: result["audit"][key] for key in _AUDIT_KEYS}
    get_audit_logger().log_from_request(
        actor=actor,
        action=action,
        resource_type="invitation",
        resource_id=(result["invitation_id"] or "")[:12],
        metadata=meta,
    )


@invitation_bp.route("", methods=["POST"])
@require_auth
def issue_invitation():
    actor = _principal()
    try:
        result = engine.issue(current_app._db, actor, request.get_json(silent=True) or {})
    except engine.InvitationError as exc:
        return _error(exc)
    _audit(actor, "invitation.issue", result)
    status = 200 if result["http"].get("duplicate") else 201
    return jsonify(result["http"]), status


@invitation_bp.route("/<invitation_id>", methods=["GET"])
@require_auth
def inspect_invitation(invitation_id: str):
    actor = _principal()
    try:
        result = engine.inspect(current_app._db, invitation_id)
    except engine.InvitationError as exc:
        return _error(exc)
    _audit(actor, "invitation.inspect", result)
    return jsonify(result["http"])


@invitation_bp.route("/<invitation_id>/prepare-redemption", methods=["POST"])
@require_auth
def prepare_redemption(invitation_id: str):
    actor = _principal()
    try:
        result = engine.prepare(current_app._db, invitation_id, actor)
    except engine.InvitationError as exc:
        return _error(exc)
    _audit(actor, "invitation.prepare_redemption", result)
    return jsonify(result["http"])


@invitation_bp.route("/<invitation_id>/redeem", methods=["POST"])
@require_auth
def redeem_invitation(invitation_id: str):
    actor = _principal()
    try:
        result = engine.redeem(
            current_app._db, invitation_id, actor, request.get_json(silent=True) or {},
        )
    except engine.InvitationError as exc:
        return _error(exc)
    _audit(actor, "invitation.redeem", result)
    return jsonify(result["http"])


@invitation_bp.route("/<invitation_id>/revoke", methods=["POST"])
@require_auth
def revoke_invitation(invitation_id: str):
    actor = _principal()
    try:
        result = engine.revoke(current_app._db, invitation_id, actor)
    except engine.InvitationError as exc:
        return _error(exc)
    _audit(actor, "invitation.revoke", result)
    return jsonify(result["http"])


@credential_bp.route("", methods=["POST"])
@require_auth
def enroll_credential():
    actor = _principal()
    try:
        result = engine.enroll_credential(current_app._db, actor, request.get_json(silent=True) or {})
    except engine.InvitationError as exc:
        return _error(exc)
    get_audit_logger().log_from_request(
        actor=actor,
        action="device_credential.enroll",
        resource_type="device_credential",
        resource_id=result["credential_id"][:12],
        metadata={"audience": result["audience"], "verifier_ref": result["verifier_ref"]},
    )
    return jsonify(result), 201
