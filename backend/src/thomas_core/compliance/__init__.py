"""
Compliance Gate — PIPL-compliant consent, audit, and PII redaction layer.
L1 合规底座：授权、审计留痕、脱敏、留存策略

Usage:
    from src.thomas_core.compliance.consent import require_consent
    from src.thomas_core.compliance.redact import redact_pii
    from src.thomas_core.compliance.audit import AuditLogger

    @require_consent('resume_upload')
    def parse_resume(user_id, resume_text): ...

    safe_text = redact_pii(user_input)
    audit.log(user_id=..., action='resume_parse', resource_type='resume', ...)
"""