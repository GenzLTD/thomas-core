"""设备证明插槽。

默认关闭：任何证明都不通过。测试可把 THOMAS_DEVICE_VERIFIER 设为 stub。
stub 只核对一次性挑战的摘要，不代表戒指或穿戴已经具备硬件证明。
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


def current_verifier() -> DeviceVerifier:
    mode = os.getenv("THOMAS_DEVICE_VERIFIER", "closed").strip().lower()
    if mode == "stub":
        return StubVerifier()
    return ClosedVerifier()
