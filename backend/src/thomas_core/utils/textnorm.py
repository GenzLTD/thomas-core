"""
Chinese Simplified <-> Traditional text normalization for retrieval.

The poetry corpus is stored in Traditional Chinese (繁体), while user queries
often arrive in Simplified Chinese (简体). ChromaDB's default embedding
(all-MiniLM-L6-v2) is sensitive to glyph differences (举 vs 舉, 床 vs 牀),
so a 简体 query misses 繁体 documents.

We normalize query text to Traditional (s2t) *before* embedding, which aligns
the query vector with the corpus vector space. The conversion is idempotent for
already-traditional input.

Uses `opencc-python-reimplemented` (pure Python, no native/system deps) when
available; gracefully falls back to returning the input unchanged if missing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("looma.textnorm")

_cc_s2t = None
_cc_loaded = False


def _get_s2t():
    """Lazily build the OpenCC s2t converter (module-level singleton)."""
    global _cc_s2t, _cc_loaded
    if _cc_loaded:
        return _cc_s2t
    _cc_loaded = True
    try:
        from opencc import OpenCC

        _cc_s2t = OpenCC("s2t")
        logger.info("OpenCC s2t converter initialized")
    except Exception as e:  # noqa: BLE001
        _cc_s2t = None
        logger.warning(
            "OpenCC unavailable, s2t normalization disabled: %s", e
        )
    return _cc_s2t


def to_traditional(text: str | None) -> str | None:
    """Convert Simplified Chinese text to Traditional Chinese.

    Idempotent for already-traditional text. Returns the input unchanged
    (or None) when OpenCC is unavailable or conversion fails.
    """
    if not text:
        return text
    cc = _get_s2t()
    if cc is None:
        return text
    try:
        return cc.convert(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("s2t conversion failed for %r: %s", text[:50], e)
        return text
