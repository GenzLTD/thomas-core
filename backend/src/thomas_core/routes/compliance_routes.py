"""
Compliance Gate: Flask routes for consent management.
"""
from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify, g
from src.thomas_core.auth.decorators import require_auth
from src.thomas_core.compliance.consent import (
    get_consent_manager,
    ALL_SCOPES,
    PRIMARY_TIERS,
    CONSENT_PACKAGES,
    SCOPE_LABELS_ZH,
)
from src.thomas_core.compliance.audit import get_audit_logger

logger = logging.getLogger("looma.compliance.routes")
compliance_bp = Blueprint("compliance", __name__)


@compliance_bp.route("/consent/grant", methods=["POST"])
@require_auth
def grant_consent():
    body = request.get_json(silent=True) or {}
    uid = getattr(g, "user_id", None)
    if not uid:
        return jsonify(error="unauthorized", message="请先登录"), 401
    scopes = body.get("scopes")
    purpose = body.get("purpose", "")
    if scopes and isinstance(scopes, list):
        c = get_consent_manager()
        r = c.grant_batch(uid, scopes, ip=request.remote_addr or "",
                         user_agent=request.headers.get("User-Agent", ""))
        a = get_audit_logger()
        a.log_from_request(actor=uid, action="consent_grant_batch",
                          resource_type="consent",
                          metadata={"scopes": scopes, "granted": r["granted"]})
        return jsonify(r)
    scope = body.get("scope", "")
    if not scope:
        return jsonify(error="missing_scope", message="请指定 scope"), 400
    if scope not in ALL_SCOPES:
        return jsonify(error="invalid_scope", message=f"未知: {scope}",
                       valid_scopes=sorted(ALL_SCOPES)), 400
    c = get_consent_manager()
    r = c.grant(uid, scope, ip=request.remote_addr or "",
               user_agent=request.headers.get("User-Agent", ""), purpose=purpose)
    a = get_audit_logger()
    a.log_from_request(actor=uid, action="consent_grant", resource_type="consent",
                      resource_id=r.get("consent_id", ""),
                      metadata={"scope": scope})
    return jsonify(r)


@compliance_bp.route("/consent/revoke", methods=["POST"])
@require_auth
def revoke_consent():
    body = request.get_json(silent=True) or {}
    uid = getattr(g, "user_id", None)
    if not uid:
        return jsonify(error="unauthorized", message="请先登录"), 401
    scope = body.get("scope", "")
    if not scope:
        return jsonify(error="missing_scope", message="请指定 scope"), 400
    c = get_consent_manager()
    r = c.revoke(uid, scope)
    a = get_audit_logger()
    a.log_from_request(actor=uid, action="consent_revoke",
                      resource_type="consent", metadata={"scope": scope})
    return jsonify(r)


@compliance_bp.route("/consent/status", methods=["GET"])
@require_auth
def consent_status():
    uid = getattr(g, "user_id", None)
    if not uid:
        return jsonify(error="unauthorized", message="请先登录"), 401
    c = get_consent_manager()
    consents = c.get_user_consents(uid)
    sm = c.status_map(uid)
    return jsonify(
        user_id=uid,
        consents=consents,
        status=sm,
        primary_tiers=list(PRIMARY_TIERS),
        packages={k: sorted(v) for k, v in CONSENT_PACKAGES.items()},
    )


@compliance_bp.route("/consent/required", methods=["GET"])
def required_consents():
    return jsonify(
        available_scopes=sorted(ALL_SCOPES),
        primary_tiers=list(PRIMARY_TIERS),
        packages={k: sorted(v) for k, v in CONSENT_PACKAGES.items()},
        details={s: SCOPE_LABELS_ZH.get(s, s) for s in sorted(ALL_SCOPES)},
    )