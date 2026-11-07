"""
Embedding generation — multi-provider fallback (Ollama, DeepSeek, OpenAI).
Migrated from old embeddings.py, adapted for Flask.
"""
from __future__ import annotations
import logging
import requests
from flask import current_app

logger = logging.getLogger("looma.embeddings")


def get_embedding(text: str) -> list[float] | None:
    """Generate embedding for a text string.

    Tries providers in EMBED_PROVIDER_ORDER until one succeeds.
    Returns 768-d float vector or None on failure.
    """
    config = current_app.config
    provider_order = [p.strip().lower() for p in config.get("EMBED_PROVIDER_ORDER", "ollama,deepseek").split(",")]

    for provider in provider_order:
        try:
            if provider == "ollama":
                return _ollama_embed(text, config)
            elif provider == "deepseek":
                # DeepSeek doesn't have a dedicated embedding API, skip
                continue
            elif provider == "openai":
                return _openai_embed(text, config)
        except Exception as e:
            logger.warning(f"Embedding provider {provider} failed: {e}")
            continue

    logger.error("All embedding providers unavailable")
    return None


def _ollama_embed(text: str, config) -> list[float] | None:
    """Generate embedding via Ollama."""
    host = config.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = config.get("EMBED_MODEL", "nomic-embed-text:latest")

    url = f"{host.rstrip('/')}/api/embeddings"
    payload = {"model": model, "prompt": text}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("embedding")


def _openai_embed(text: str, config) -> list[float] | None:
    """Generate embedding via OpenAI-compatible API."""
    api_key = config.get("OPENAI_API_KEY", "")
    base_url = config.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = config.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    if not api_key:
        return None

    url = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": text}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]
