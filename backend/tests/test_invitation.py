"""P1 邀请状态机。not_required，本区，不读宿主租户表。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

_EMAIL_ENV = (
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY",
    "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWT_SECRET",
    "DEEPSEEK_API_KEY",
)


def boot(tmp_path, *, secret: str = "", strict: str = "0"):
    os.environ["DATABASE_PATH"] = str(tmp_path / "core.db")
    os.environ["THOMAS_SCHEMA_SPLIT"] = "1"
    os.environ["THOMAS_SCHEMA_STRICT"] = strict
    os.environ["PROFILE_EMBED"] = "deterministic"
    os.environ["ETHOS_AUTH_SECRET"] = secret
    os.environ.pop("THOMAS_DEVICE_VERIFIER", None)
    for key in _EMAIL_ENV:
        os.environ.pop(key, None)
    from src.thomas_core.compliance.audit import reset_audit_logger
    from src.thomas_core.app import create_core_app

    reset_audit_logger()
    app = create_core_app()
    app.config["PROPAGATE_EXCEPTIONS"] = True
    return app, Path(os.environ["DATABASE_PATH"])


def register(client, email: str):
    created = client.post("/v1/auth/register", json={
        "email": email, "password": "Passw0rd!", "name": "t",
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    user_id = created.get_json()["user"]["id"]
    token = client.post("/v1/auth/login", json={
        "email": email, "password": "Passw0rd!",
    }).get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def issue(client, headers, key: str, **extra):
    body = {"idempotency_key": key}
    body.update(extra)
    return client.post("/v1/invitations", headers=headers, json=body)


def redeem(client, headers, invitation_id: str, key: str, **extra):
    body = {
        "idempotency_key": key,
        "audience": "genzer.terminal.registration",
        "purpose": "account_registration",
    }
    body.update(extra)
    return client.post(f"/v1/invitations/{invitation_id}/redeem", headers=headers, json=body)


def test_cold_start_creates_seed_and_fourteen_tables(tmp_path):
    app, db_path = boot(tmp_path)
    assert app.test_client().get("/health").status_code == 200
    conn = sqlite3.connect(db_path)
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}
    seed = conn.execute(
        """SELECT issue_allowed, device_policy FROM tenant_audience_policies
           WHERE tenant = ? AND audience = ? AND purpose = ?""",
        ("genzer.terminal", "genzer.terminal.registration", "account_registration"),
    ).fetchone()
    conn.close()
    assert names == {
        "users", "user_identities", "consents", "audit_logs",
        "signal_ingest", "signal_outbox", "signal_dlq",
        "profile_events", "schema_meta",
        "invitations", "invitation_redemptions", "tenant_audience_policies",
        "device_challenges", "device_credentials",
    }
    assert seed == (1, "not_required")


def test_existing_db_strict_boot_rebuilds_invitation_tables(tmp_path):
    app, db_path = boot(tmp_path)
    assert app.test_client().get("/health").status_code == 200
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE invitation_redemptions")
    conn.execute("DROP TABLE invitations")
    conn.execute("DROP TABLE tenant_audience_policies")
    conn.execute("UPDATE schema_meta SET version = 'stale' WHERE scope = 'core'")
    conn.commit()
    conn.close()

    os.environ["THOMAS_SCHEMA_STRICT"] = "1"
    from src.thomas_core.app import create_core_app
    from src.thomas_core.db.schema_loader import ensure_scope

    restarted = create_core_app()
    assert restarted.test_client().get("/health").status_code == 200
    conn = sqlite3.connect(db_path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    version = conn.execute("SELECT version FROM schema_meta WHERE scope = 'core'").fetchone()[0]
    conn.close()
    assert {
        "invitations", "invitation_redemptions", "tenant_audience_policies",
        "device_challenges", "device_credentials",
    } <= names
    assert version != "stale"
    again = ensure_scope(str(db_path), "core", strict=True)
    assert again["drift"] is False


def test_issue_inspect_prepare_redeem_and_duplicate(tmp_path):
    app, _db_path = boot(tmp_path)
    client = app.test_client()
    headers, user_id = register(client, "one@example.com")
    created = issue(client, headers, "issue-1", issuer_sub="attacker", email="hidden@example.com")
    assert created.status_code == 201, created.get_data(as_text=True)
    payload = created.get_json()
    invitation = payload["invitation"]
    invitation_id = invitation["id"]
    assert payload["duplicate"] is False
    assert invitation["issuer"] == {"sub": user_id}
    assert invitation["device_policy"] == {"mode": "not_required"}
    assert "hidden@example.com" not in created.get_data(as_text=True)

    replay = issue(client, headers, "issue-1")
    assert replay.status_code == 200
    assert replay.get_json()["duplicate"] is True
    assert replay.get_json()["invitation"]["id"] == invitation_id

    inspected = client.get(f"/v1/invitations/{invitation_id}", headers=headers)
    assert inspected.status_code == 200
    assert "issuer" not in inspected.get_json()["invitation"]

    prepared = client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers)
    assert prepared.status_code == 200
    assert prepared.get_json()["consumes_invitation"] is False
    assert prepared.get_json()["challenge"] is None

    first = redeem(client, headers, invitation_id, "redeem-1")
    assert first.status_code == 200, first.get_data(as_text=True)
    body = first.get_json()
    assert body["duplicate"] is False
    assert body["redemption_count"] == 1
    assert body["redemption"]["redeemer"] == {"sub": user_id}
    assert body["redemption"]["device_verification"] == {"required": False, "verified": False}
    assert "access_token" not in body

    second = redeem(client, headers, invitation_id, "redeem-1")
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    assert second.get_json()["redemption_count"] == 1
    assert second.get_json()["redemption"]["redeemed_at"] == body["redemption"]["redeemed_at"]


def test_expired_revoked_exhausted_and_scope_errors(tmp_path):
    app, db_path = boot(tmp_path)
    client = app.test_client()
    issuer, _issuer_id = register(client, "issuer@example.com")
    other, other_id = register(client, "other@example.com")
    third, _third_id = register(client, "third@example.com")

    expired = issue(client, issuer, "exp")
    expired_id = expired.get_json()["invitation"]["id"]
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE invitations SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00Z", expired_id))
    conn.commit()
    conn.close()
    assert redeem(client, issuer, expired_id, "exp-redeem").status_code == 410
    seen = client.get(f"/v1/invitations/{expired_id}", headers=issuer).get_json()["invitation"]["status"]
    assert seen == "expired"

    revoked = issue(client, issuer, "rev")
    revoked_id = revoked.get_json()["invitation"]["id"]
    assert client.post(f"/v1/invitations/{revoked_id}/revoke", headers=other).status_code == 403
    assert client.post(f"/v1/invitations/{revoked_id}/revoke", headers=issuer).status_code == 200
    assert redeem(client, other, revoked_id, "rev-redeem").status_code == 409

    shared = issue(client, issuer, "max", max_redemptions=2)
    shared_id = shared.get_json()["invitation"]["id"]
    assert redeem(client, issuer, shared_id, "max-1").status_code == 200
    assert redeem(client, issuer, shared_id, "max-1b").status_code == 409
    assert redeem(client, other, shared_id, "max-2").status_code == 200
    assert redeem(client, third, shared_id, "max-3").status_code == 409

    mismatch = issue(client, issuer, "scope")
    mismatch_id = mismatch.get_json()["invitation"]["id"]
    wrong = redeem(client, other, mismatch_id, "scope-redeem", audience="gfcc.circle", purpose="circle_admission")
    assert wrong.status_code == 422

    limited = issue(client, issuer, "who", recipient_sub=other_id)
    limited_id = limited.get_json()["invitation"]["id"]
    assert redeem(client, issuer, limited_id, "who-issuer").status_code == 403
    assert redeem(client, other, limited_id, "who-other").status_code == 200

    denied = issue(client, issuer, "nope", tenant="genzer.terminal", audience="gfcc.circle", purpose="circle_admission")
    assert denied.status_code == 403
    assert client.get(f"/v1/invitations/{mismatch_id}").status_code == 401
    assert client.post("/v1/invitations", json={"idempotency_key": "anon"}).status_code == 401


def test_registered_device_policy_fails_closed(tmp_path):
    app, db_path = boot(tmp_path)
    client = app.test_client()
    headers, user_id = register(client, "device@example.com")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """UPDATE tenant_audience_policies SET device_policy = 'registered_credential_required'
           WHERE tenant = 'genzer.terminal'"""
    )
    conn.commit()
    conn.close()
    created = issue(client, headers, "device")
    assert created.status_code == 201
    invitation_id = created.get_json()["invitation"]["id"]
    prepared = client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers)
    challenge = (prepared.get_json() or {}).get("challenge") or {}
    redeemed = redeem(client, headers, invitation_id, "device-redeem", device_proof={
        "challenge_id": challenge.get("challenge_id"),
        "credential_id": "unregistered-ring",
        "proof": "not-a-proof",
    })
    assert prepared.status_code == 200
    assert challenge.get("nonce")
    assert challenge.get("principal_binding") == user_id
    assert redeemed.status_code == 409
    conn = sqlite3.connect(db_path)
    count, status = conn.execute(
        "SELECT redemption_count, status FROM invitations WHERE id = ?", (invitation_id,)
    ).fetchone()
    redemptions = conn.execute(
        "SELECT COUNT(*) FROM invitation_redemptions WHERE invitation_id = ?", (invitation_id,)
    ).fetchone()[0]
    conn.close()
    assert (count, status, redemptions) == (0, "active", 0)


def test_audit_rows_do_not_carry_email_or_full_handle(tmp_path):
    app, db_path = boot(tmp_path)
    client = app.test_client()
    email = "audit@example.com"
    headers, user_id = register(client, email)
    created = issue(client, headers, "audit-issue")
    invitation_id = created.get_json()["invitation"]["id"]
    assert client.get(f"/v1/invitations/{invitation_id}", headers=headers).status_code == 200
    assert client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers).status_code == 200
    assert redeem(client, headers, invitation_id, "audit-redeem").status_code == 200
    revoked = issue(client, headers, "audit-revoke")
    revoked_id = revoked.get_json()["invitation"]["id"]
    assert client.post(f"/v1/invitations/{revoked_id}/revoke", headers=headers).status_code == 200

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT action, actor, resource_id, metadata FROM audit_logs
           WHERE resource_type = 'invitation'"""
    ).fetchall()
    conn.close()
    seen = {row[0] for row in rows}
    assert seen == {
        "invitation.issue", "invitation.inspect", "invitation.prepare_redemption",
        "invitation.redeem", "invitation.revoke",
    }
    for action, actor, resource_id, metadata in rows:
        assert actor == user_id
        assert email not in actor
        assert email not in (metadata or "")
        assert invitation_id not in (metadata or "")
        assert resource_id == invitation_id[:12] or resource_id == revoked_id[:12]
        assert set(json.loads(metadata)) == {"tenant", "audience", "purpose", "device_policy"}
        assert action.startswith("invitation.")


def test_health_reports_bridge_without_echoing_secret(tmp_path):
    secret = "bridge-sentinel-value"
    app, _db_path = boot(tmp_path, secret=secret)
    response = app.test_client().get("/health")
    assert response.get_json()["bridge_configured"] is True
    assert response.get_json()["core_blueprints"] == ["auth", "ask", "compliance"]
    assert secret not in response.get_data(as_text=True)

    empty, _db_path = boot(tmp_path / "empty", secret="")
    assert empty.test_client().get("/health").get_json()["bridge_configured"] is False


def test_redeem_and_revoke_only_one_terminal_state(tmp_path):
    app, db_path = boot(tmp_path)
    client = app.test_client()
    headers, user_id = register(client, "race@example.com")
    created = issue(client, headers, "race-issue")
    invitation_id = created.get_json()["invitation"]["id"]
    from src.thomas_core.db.core_db import CoreDB
    from src.thomas_core.invitation import engine

    db = CoreDB(str(db_path))
    barrier = threading.Barrier(2)
    outcomes = []

    def run(kind: str) -> None:
        barrier.wait()
        try:
            if kind == "redeem":
                engine.redeem(db, invitation_id, user_id, {
                    "idempotency_key": "race-redeem",
                    "audience": "genzer.terminal.registration",
                    "purpose": "account_registration",
                })
            else:
                engine.revoke(db, invitation_id, user_id)
            outcomes.append(200)
        except engine.InvitationError as exc:
            outcomes.append(exc.status)

    threads = [threading.Thread(target=run, args=(kind,)) for kind in ("redeem", "revoke")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == [200, 409]
    conn = sqlite3.connect(db_path)
    status, count = conn.execute(
        "SELECT status, redemption_count FROM invitations WHERE id = ?", (invitation_id,)
    ).fetchone()
    redemptions = conn.execute(
        "SELECT COUNT(*) FROM invitation_redemptions WHERE invitation_id = ?", (invitation_id,)
    ).fetchone()[0]
    conn.close()
    assert (status, count, redemptions) in {("exhausted", 1, 1), ("revoked", 0, 0)}


def test_core_source_does_not_import_ethos_or_query_from_routes():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import ethos" not in text, path
        assert "from ethos" not in text, path
    routes = (SRC / "thomas_core" / "routes" / "invitation_routes.py").read_text(encoding="utf-8")
    assert "SELECT" not in routes
    assert "INSERT" not in routes
