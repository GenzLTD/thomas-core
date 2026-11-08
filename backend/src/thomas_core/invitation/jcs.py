"""RFC 8785 JSON Canonicalization Scheme.

对象键按 UTF-16 码元排序。数字沿用 ECMAScript 的 JSON 数字写法。
非有限数字，以及超出安全整数范围的整数，直接拒绝，避免两边各自猜格式。
"""
from __future__ import annotations

import json
import math

_SAFE_INT = 9007199254740991


class JcsError(ValueError):
    pass


def canonicalize(value) -> bytes:
    return _emit(value).encode("utf-8")


def _emit(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int):
        if abs(value) > _SAFE_INT:
            raise JcsError("integer is outside the safe range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JcsError("number must be finite")
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_emit(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise JcsError("object keys must be strings")
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
        return "{" + ",".join(_string(key) + ":" + _emit(item) for key, item in items) + "}"
    raise JcsError("value cannot be canonicalized")


def _string(value: str) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
