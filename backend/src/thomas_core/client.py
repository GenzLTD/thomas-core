"""核调用客户端（Phase 1）：product → core 的 HTTP 通路。

`THOMAS_CORE_MODE`：
- `inprocess`（默认）：product 与 core 同进程，路由直接由 `thomas_core.routes.*` 蓝图提供；
- `http`：宿主不注册核蓝图，改由 `src/api/routes/core_proxy_routes.py` 经本模块转发到核进程。

`THOMAS_CORE_URL` 默认 `http://127.0.0.1:5300`。
超时：`/v1/ask` 走真 LLM（最长 240s），其余 60s。
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

FORWARD_HEADERS = ("authorization", "content-type", "x-user-id", "accept", "x-request-id")
ASK_TIMEOUT = 240
DEFAULT_TIMEOUT = 60


def mode() -> str:
    return os.getenv("THOMAS_CORE_MODE", "inprocess").strip().lower()


def http_mode() -> bool:
    return mode() == "http"


def base_url() -> str:
    return os.getenv("THOMAS_CORE_URL", "http://127.0.0.1:5300").rstrip("/")


def timeout_for(path: str) -> int:
    return ASK_TIMEOUT if path.startswith("/v1/ask") else DEFAULT_TIMEOUT


def forward(method: str, path: str, body: bytes | None = None,
            headers: dict | None = None, query: str = "") -> tuple[int, bytes, str]:
    """把一次调用转发给核进程，返回 (status, body_bytes, content_type)。

    仅在 `THOMAS_CORE_MODE=http` 且核进程可达时使用；不可达抛 `CoreUnreachable`。
    """
    url = base_url() + path + (("?" + query) if query else "")
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        if value:
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout_for(path)) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        return exc.code, raw, ctype


class CoreUnreachable(RuntimeError):
    def __init__(self, message: str, url: str):
        super().__init__(message)
        self.url = url
