"""核侧 LLM 调用（含隐私轨 allowed_providers 闸门）。"""
from __future__ import annotations

import logging
from typing import Any

import requests
from flask import current_app

logger = logging.getLogger("thomas_core.llm")


def call_llm(
    prompt: str,
    *,
    temperature: float = 0.3,
    allowed_providers: tuple[str, ...] | list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """按 LLM_PROVIDER_ORDER 尝试生成；allowed_providers 收窄可用通道（local_only→仅 ollama）。"""
    config = current_app.config
    provider_order = [
        p.strip().lower()
        for p in (config.get("LLM_PROVIDER_ORDER") or "deepseek,ollama").split(",")
        if p.strip()
    ]
    if allowed_providers is not None:
        allow_list = [p.strip().lower() for p in allowed_providers if p and str(p).strip()]
        allow_set = set(allow_list)
        filtered = [p for p in provider_order if p in allow_set]
        for p in allow_list:
            if p not in filtered:
                filtered.append(p)
        provider_order = filtered

    timeout = float(config.get("API_REQUEST_TIMEOUT", 90))
    for provider in provider_order:
        try:
            if provider == "deepseek":
                api_key = (config.get("DEEPSEEK_API_KEY") or "").strip()
                if not api_key or api_key.lower() in ("skip", "your-deepseek-api-key"):
                    continue
                url = f"{(config.get('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com/v1').rstrip('/')}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                model = config.get("DEEPSEEK_MODEL") or "deepseek-chat"
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                text = msg.get("content") or msg.get("reasoning_content") or ""
            elif provider == "ollama":
                host = config.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
                url = f"{str(host).rstrip('/')}/api/generate"
                model = config.get("OLLAMA_MODEL") or "qwen2.5-coder:1.5b"
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                resp = requests.post(url, json=payload, timeout=timeout)
                resp.raise_for_status()
                text = (resp.json() or {}).get("response") or ""
            else:
                continue
            if meta is not None:
                meta["provider"] = provider
                meta["model"] = model
            return text
        except Exception as e:
            logger.warning("LLM provider %s failed: %s", provider, e)
            continue
    if meta is not None:
        meta.setdefault("provider", None)
    return None
