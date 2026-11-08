"""设备证明插槽。

默认关闭：任何证明都不通过。
stub 只核对一次性挑战的摘要。hmac 才进入认账：参数哈希、重放和计数器。
两者都不是证书，也不是硅根。
"""
from __future__ import annotations

import hashlib
import os
from typing import Protocol


class DeviceVerifier(Protocol):
    name: str

    def verify(self, *, nonce: str, challenge_id: str, credential_id: str, proof: str) -> bool:
        """证明是否对得上这次挑战。"""


class ClosedVerifier:
    name = "closed"

    def verify(self, *, nonce: str, challenge_id: str, credential_id: str, proof: str) -> bool:
        return False


class StubVerifier:
    name = "stub"

    def verify(self, *, nonce: str, challenge_id: str, credential_id: str, proof: str) -> bool:
        expected = stub_proof(nonce, credential_id, challenge_id)
        return proof == expected


def stub_proof(nonce: str, credential_id: str, challenge_id: str) -> str:
    raw = f"{nonce}:{credential_id}:{challenge_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class HmacVerifier:
    name = "hmac"

    def verify(self, *, nonce: str, challenge_id: str, credential_id: str, proof: str) -> bool:
        return False


def current_verifier() -> DeviceVerifier:
    mode = os.getenv("THOMAS_DEVICE_VERIFIER", "closed").strip().lower()
    if mode == "stub":
        return StubVerifier()
    if mode == "hmac":
        return HmacVerifier()
    return ClosedVerifier()
