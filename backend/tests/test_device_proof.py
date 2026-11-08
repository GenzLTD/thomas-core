"""P2 设备证明信封。默认验证器关闭。stub 只在测试里打开。"""
from __future__ import annotations

import os
import sqlite3

from src.thomas_core.invitation.verifier import stub_proof
from test_invitation import boot, issue, redeem, register

AUDIENCE = "genzer.terminal.registration"
PURPOSE = "device_proof"


def _policy(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR IGNORE INTO tenant_audience_policies
           (tenant, audience, purpose, issue_allowed, device_policy)
           VALUES ('genzer.terminal', ?, ?, 1, 'registered_credential_required')""",
        (AUDIENCE, PURPOSE),
    )
    conn.commit()
    conn.close()


def _issue(client, headers, key, **extra):
    return issue(
        client, headers, key,
        tenant="genzer.terminal", audience=AUDIENCE, purpose=PURPOSE, **extra,
    )


def _redeem(client, headers, invitation_id, key, challenge, credential_id, proof):
    return redeem(
        client, headers, invitation_id, key,
        audience=AUDIENCE, purpose=PURPOSE,
        device_proof={
            "challenge_id": challenge["challenge_id"],
            "credential_id": credential_id,
            "proof": proof,
        },
    )


def test_closed_verifier_rejects_the_stub_digest(tmp_path):
    app, db_path = boot(tmp_path)
    client = app.test_client()
    headers, user_id = register(client, "closed@example.com")
    _policy(db_path)
    created = _issue(client, headers, "closed-issue")
    invitation_id = created.get_json()["invitation"]["id"]
    enrolled = client.post("/v1/device-credentials", headers=headers, json={
        "credential_id": "ring-closed",
        "audience": AUDIENCE,
        "principal_binding": "client-chosen",
    })
    assert enrolled.status_code == 201
    assert enrolled.get_json()["verifier_ref"] == "closed"
    prepared = client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers)
    challenge = prepared.get_json()["challenge"]
    assert challenge["principal_binding"] == user_id
    proof = stub_proof(challenge["nonce"], "ring-closed", challenge["challenge_id"])
    rejected = _redeem(client, headers, invitation_id, "closed-redeem", challenge, "ring-closed", proof)
    assert rejected.status_code == 409
    assert rejected.get_json()["error"] == "device_proof_rejected"


def test_stub_verifier_accepts_one_challenge_then_closes_it(tmp_path):
    os.environ["THOMAS_DEVICE_VERIFIER"] = "stub"
    try:
        app, db_path = boot(tmp_path)
        os.environ["THOMAS_DEVICE_VERIFIER"] = "stub"
        client = app.test_client()
        headers, user_id = register(client, "stub@example.com")
        other_headers, _other = register(client, "other@example.com")
        _policy(db_path)
        created = _issue(client, headers, "stub-issue", max_redemptions=2)
        invitation_id = created.get_json()["invitation"]["id"]
        enrolled = client.post("/v1/device-credentials", headers=headers, json={
            "credential_id": "ring-stub",
            "audience": AUDIENCE,
        })
        assert enrolled.status_code == 201
        assert enrolled.get_json()["verifier_ref"] == "stub"
        again = client.post("/v1/device-credentials", headers=headers, json={
            "credential_id": "ring-stub",
            "audience": AUDIENCE,
        })
        assert again.status_code == 201
        stolen = client.post("/v1/device-credentials", headers=other_headers, json={
            "credential_id": "ring-stub",
            "audience": AUDIENCE,
        })
        assert stolen.status_code == 409

        prepared = client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers)
        challenge = prepared.get_json()["challenge"]
        proof = stub_proof(challenge["nonce"], "ring-stub", challenge["challenge_id"])
        missing = redeem(
            client, headers, invitation_id, "missing-proof",
            audience=AUDIENCE, purpose=PURPOSE,
        )
        assert missing.status_code == 409
        assert missing.get_json()["error"] == "device_proof_required"
        accepted = _redeem(client, headers, invitation_id, "stub-redeem", challenge, "ring-stub", proof)
        body = accepted.get_json()
        assert accepted.status_code == 200
        assert body["redemption"]["device_verification"] == {
            "required": True,
            "verified": True,
            "credential_id": "ring-stub",
        }
        assert "access_token" not in body
        assert body["redemption"]["redeemer"]["sub"] == user_id
        reused = _redeem(client, headers, invitation_id, "stub-reuse", challenge, "ring-stub", proof)
        assert reused.status_code == 409
        assert reused.get_json()["error"] == "challenge_reused"

        other_prepare = client.post(
            f"/v1/invitations/{invitation_id}/prepare-redemption", headers=other_headers,
        )
        other_challenge = other_prepare.get_json()["challenge"]
        other_proof = stub_proof(other_challenge["nonce"], "ring-stub", other_challenge["challenge_id"])
        crossed = _redeem(
            client, other_headers, invitation_id, "other-redeem",
            other_challenge, "ring-stub", other_proof,
        )
        assert crossed.status_code == 409

        fresh = client.post(f"/v1/invitations/{invitation_id}/prepare-redemption", headers=headers)
        fresh_challenge = fresh.get_json()["challenge"]
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE device_challenges SET expires_at = ? WHERE challenge_id = ?",
            ("2000-01-01T00:00:00Z", fresh_challenge["challenge_id"]),
        )
        conn.commit()
        conn.close()
        expired_proof = stub_proof(
            fresh_challenge["nonce"], "ring-stub", fresh_challenge["challenge_id"],
        )
        expired = _redeem(
            client, headers, invitation_id, "expired-challenge",
            fresh_challenge, "ring-stub", expired_proof,
        )
        assert expired.status_code == 409
        assert expired.get_json()["error"] == "challenge_expired"
        conn = sqlite3.connect(db_path)
        count, status = conn.execute(
            "SELECT redemption_count, status FROM invitations WHERE id = ?",
            (invitation_id,),
        ).fetchone()
        conn.close()
        assert (count, status) == (1, "active")
    finally:
        os.environ.pop("THOMAS_DEVICE_VERIFIER", None)
