"""认账用的过渡证明。

证书和 EST 不在这里。预共享 HMAC 只在 THOMAS_DEVICE_VERIFIER=hmac
且密钥足够长时启用。业务参数由服务端按 JCS 重算，不信调用方自报的哈希。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timezone

from .jcs import canonicalize

_TYP = "thomas-pop+hmac"
_ALG = "HS256"
_OP = "invitation.redeem"
_JTI = re.compile(r"^[A-Za-z0-9_-]{22}$")
_HASH = re.compile(r"^[A-Za-z0-9_-]{43}$")
_FORBIDDEN_KEYS = {
    "000102030405060708090a0b0c0d0e0f",
    "000102030405060708090a0b0c0d0e0f000102030405060708090a0b0c0d0e0f",
}


class PopError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def hmac_key() -> bytes | None:
    raw = os.getenv("THOMAS_DEVICE_HMAC_KEY", "").strip()
    if raw in _FORBIDDEN_KEYS or len(raw.encode("utf-8")) < 32:
        return None
    return raw.encode("utf-8")


def redeem_args(
    *,
    invitation_id: str,
    audience: str,
    purpose: str,
    credential_id: str,
    challenge_id: str,
    idem: str,
) -> dict:
    return {
        "audience": audience,
        "challenge_id": challenge_id,
        "credential_id": credential_id,
        "idem": idem,
        "invitation_id": invitation_id,
        "op": _OP,
        "purpose": purpose,
    }


def args_hash(args: dict) -> str:
    return _b64url(hashlib.sha256(canonicalize(args)).digest())


def sign_pop(key: bytes, claims: dict) -> str:
    return _b64url(hmac.new(key, canonicalize(claims), hashlib.sha256).digest())


def build_redeem_pop(
    key: bytes,
    *,
    invitation_id: str,
    audience: str,
    purpose: str,
    credential_id: str,
    challenge_id: str,
    nonce: str,
    idem: str,
    jti: str,
    cnt: int,
    iat: int,
) -> tuple[dict, str]:
    claims = _claims({
        "typ": _TYP,
        "alg": _ALG,
        "iat": iat,
        "exp": iat + 60,
        "jti": jti,
        "cnt": cnt,
        "chn": nonce,
        "bnd": {
            "op": _OP,
            "res": f"urn:thomas:invitation:{invitation_id}",
            "args_hash": args_hash(redeem_args(
                invitation_id=invitation_id,
                audience=audience,
                purpose=purpose,
                credential_id=credential_id,
                challenge_id=challenge_id,
                idem=idem,
            )),
            "args_c14n": "JCS",
            "idem": idem,
        },
    })
    return claims, sign_pop(key, claims)


def verify_redeem_pop(
    db,
    conn,
    *,
    invitation_id: str,
    audience: str,
    purpose: str,
    credential_id: str,
    challenge_id: str,
    nonce: str,
    idem: str,
    pop: dict,
    mac: str,
    now: datetime,
) -> None:
    key = hmac_key()
    if key is None:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    claims = _claims(pop)
    if claims.get("chn") != nonce:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    _clock(claims, now)
    bnd = claims["bnd"]
    if bnd.get("idem") != idem or bnd.get("op") != _OP:
        raise PopError(422, "device_args_rejected", "signed arguments do not match")
    if bnd.get("res") != f"urn:thomas:invitation:{invitation_id}":
        raise PopError(422, "device_args_rejected", "signed arguments do not match")
    expected = args_hash(redeem_args(
        invitation_id=invitation_id,
        audience=audience,
        purpose=purpose,
        credential_id=credential_id,
        challenge_id=challenge_id,
        idem=idem,
    ))
    if bnd.get("args_hash") != expected or bnd.get("args_c14n") != "JCS":
        raise PopError(422, "device_args_rejected", "signed arguments do not match")
    if not hmac.compare_digest(sign_pop(key, claims), mac):
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    if db.pop_jti_seen(conn, claims["jti"]):
        raise PopError(409, "device_proof_replayed", "proof already used")
    if not db.bump_device_counter(conn, credential_id, claims["cnt"]):
        raise PopError(409, "device_counter_rollback", "device counter moved backwards")
    db.insert_pop_replay(conn, {
        "jti": claims["jti"],
        "credential_id": credential_id,
        "expire_at": datetime.fromtimestamp(claims["exp"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def _claims(pop: dict) -> dict:
    if not isinstance(pop, dict):
        raise PopError(409, "device_proof_required", "device proof is required")
    if pop.get("typ") != _TYP or pop.get("alg") != _ALG:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    jti = pop.get("jti")
    chn = pop.get("chn")
    if not isinstance(jti, str) or not _JTI.fullmatch(jti):
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    if not isinstance(chn, str) or not chn:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    iat = pop.get("iat")
    exp = pop.get("exp")
    cnt = pop.get("cnt")
    if type(iat) is not int or type(exp) is not int or type(cnt) is not int:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    if cnt < 1:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")
    bnd = pop.get("bnd")
    if not isinstance(bnd, dict):
        raise PopError(422, "device_args_rejected", "signed arguments do not match")
    args = bnd.get("args_hash")
    if not isinstance(args, str) or not _HASH.fullmatch(args):
        raise PopError(422, "device_args_rejected", "signed arguments do not match")
    return {
        "alg": _ALG,
        "bnd": {
            "args_c14n": bnd.get("args_c14n"),
            "args_hash": args,
            "idem": bnd.get("idem"),
            "op": bnd.get("op"),
            "res": bnd.get("res"),
        },
        "chn": chn,
        "cnt": cnt,
        "exp": exp,
        "iat": iat,
        "jti": jti,
        "typ": _TYP,
    }


def _clock(claims: dict, now: datetime) -> None:
    now_ts = int(now.timestamp())
    iat = claims["iat"]
    exp = claims["exp"]
    if abs(now_ts - iat) > 60 or exp <= iat or exp - iat > 120 or exp <= now_ts:
        raise PopError(409, "device_proof_rejected", "device proof was rejected")


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
