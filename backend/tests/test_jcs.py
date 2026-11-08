"""JCS 测试向量。键序、转义、安全整数和 RFC 8785 的数字样例锁在这里。"""
from __future__ import annotations

import pytest

from src.thomas_core.invitation.jcs import JcsError, canonicalize


def test_rfc8785_number_and_string_sample():
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": "€$\u000f\nA'B\"\\\"/",
        "literals": [None, True, False],
    }
    assert canonicalize(value) == (
        '{"literals":[null,true,false],'
        '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\"/"}'
    ).encode("utf-8")


def test_sorts_object_keys_by_utf16_code_units():
    encoded = canonicalize({"\uE000": 1, "\U0001F600": 2}).decode("utf-8")
    assert encoded.index("\U0001F600") < encoded.index("\uE000")


def test_escapes_line_separators_and_rejects_unsafe_numbers():
    assert canonicalize({"z": "\u2028\u2029"}) == b'{"z":"\\u2028\\u2029"}'
    assert canonicalize(2**53 - 1) == b"9007199254740991"
    with pytest.raises(JcsError):
        canonicalize(2**53)
    with pytest.raises(JcsError):
        canonicalize(float("nan"))
