"""
Compliance Gate: PII Redaction middleware.
PIPL 合规：LLM 调用前脱敏 — 姓名/身份证/手机号/邮箱替换为 token
"""
from __future__ import annotations

import logging
import re
import secrets

logger = logging.getLogger("looma.compliance.redact")

REDACTION_RULES: list[tuple[str, str, str]] = [
    ("cn_id_card",
     r"(?<!\d)\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
     "[PII_ID_{token}]"),
    ("cn_mobile",
     r"(?<!\d)1[3-9]\d{9}(?!\d)",
     "[PII_PHONE_{token}]"),
    ("cn_name",
     r"(?:名叫|叫|姓名[：:]?\s*|名字[：:]?\s*|我是|我是叫)\s*([\u4e00-\u9fff]{2,4})",
     "[PII_NAME_{token}]"),
    ("email",
     r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
     "[PII_EMAIL_{token}]"),
]

SAFE_WORDS = frozenset({
    "是的", "好的", "可以", "没有", "什么", "不是", "这是", "一个",
    "我们", "他们", "你们", "这个", "那个", "就是", "还是",
})


def _generate_token() -> str:
    return secrets.token_hex(4)


def redact_pii(text: str) -> tuple[str, dict[str, str]]:
    """Redact PII from text, returning (safe_text, redactions_map).
    
    Args:
        text: Raw user input that may contain PII.
    
    Returns:
        Tuple of (safe_text, redactions) where redactions is
        {token: original_value} for potential future restoration.
    """
    if not text:
        return text, {}
    
    redactions: dict[str, str] = {}
    safe_text = text
    
    for rule_name, pattern, template in REDACTION_RULES:
        def _replace(match: re.Match, _rule_name: str = rule_name,
                     _template: str = template) -> str:
            token = _generate_token()
            value = match.group(0)
            redactions[token] = value
            return _template.replace("{token}", token)
        
        try:
            safe_text = re.sub(pattern, _replace, safe_text)
        except Exception as e:
            logger.warning(f"Redaction rule '{rule_name}' failed: {e}")
    
    if redactions:
        logger.info(f"PII redacted: {len(redactions)} fields anonymized")
    return safe_text, redactions


def detect_pii(text: str) -> list[dict]:
    """Detect PII presence without redacting. Returns list of findings."""
    if not text:
        return []
    
    findings = []
    for rule_name, pattern, _template in REDACTION_RULES:
        matches = re.findall(pattern, text)
        if matches:
            findings.append({"type": rule_name, "count": len(matches)})
    return findings