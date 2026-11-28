"""
app/rag/guardrails.py — OWASP LLM01 (Prompt Injection) & LLM02 (Sensitive Output Redaction) controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Iterable

from langchain_core.documents import Document

from app.core.config import PROMPT_INJECTION_GUARD_MODE

logger = logging.getLogger("FinSight.guardrails")

# High-precision adversarial prompt injection signatures.
# Deliberately scoped to avoid false positives on routine business/finance terms.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"(?i)\b(?:ignore|disregard|forget|override|bypass)\s+"
            r"(?:all\s+|any\s+|the\s+)?(?:previous|above|prior|system|developer)\s+"
            r"(?:instructions?|directives?|prompts?|rules?|constraints?)\b"
        ),
    ),
    (
        "system_prompt_extraction",
        re.compile(
            r"(?i)\b(?:reveal|show|print|output|dump|repeat|leak)\s+"
            r"(?:me\s+)?(?:your|the)\s+(?:system\s+prompt|hidden\s+instructions?|"
            r"developer\s+prompt|initial\s+instructions?)\b"
        ),
    ),
    (
        "chat_template_smuggling",
        re.compile(r"(?i)<\|(?:im_start|im_end|system|assistant|endoftext)\|>"),
    ),
    (
        "jailbreak_persona",
        re.compile(
            r"(?i)\b(?:you\s+are\s+now|enter|switch\s+to|act\s+as)\s+"
            r"(?:DAN|developer\s+mode|unrestricted\s+mode|jailbroken)\b"
        ),
    ),
]

_EXT_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)")
_EXT_HTML_IMG_RE = re.compile(r"(?is)<img\b[^>]*\bsrc=['\"]https?://[^'\"]+['\"][^>]*>")
_HTML_COMMENT_INJECTION_RE = re.compile(
    r"(?is)<!--[\s\S]*?(?:ignore|override|system\s+prompt|instruction|exfiltrate)[\s\S]*?-->"
)

_API_KEY_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "[REDACTED-API-KEY]"),
    (
        "bearer_sk_key",
        re.compile(r"\bsk-(?:proj-|live-|test-)?[0-9A-Za-z\-_]{20,}\b"),
        "[REDACTED-API-KEY]",
    ),
    ("github_token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b"), "[REDACTED-TOKEN]"),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED-AWS-KEY]"),
    (
        "pem_private_key",
        re.compile(
            r"-----BEGIN\s+(?:[A-Z0-9]+\s+)?PRIVATE\s+KEY-----[\s\S]*?"
            r"-----END\s+(?:[A-Z0-9]+\s+)?PRIVATE\s+KEY-----"
        ),
        "[REDACTED-PRIVATE-KEY]",
    ),
    (
        "jwt_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED-JWT]",
    ),
]
_SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


@dataclass
class InjectionScanResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)
    sanitized_text: str = ""


@dataclass
class RedactionResult:
    text: str
    redacted: bool
    categories: list[str] = field(default_factory=list)


def scan_text_for_injection(text: str) -> InjectionScanResult:
    """
    Inspect untrusted document/input text for prompt-injection & exfiltration patterns,
    stripping external Markdown/HTML image trackers and malicious hidden comments.
    """
    raw = text or ""
    reasons: list[str] = []
    sanitized = raw

    if _EXT_MD_IMAGE_RE.search(sanitized):
        reasons.append("external_markdown_image")
        sanitized = _EXT_MD_IMAGE_RE.sub("[external image removed]", sanitized)
    if _EXT_HTML_IMG_RE.search(sanitized):
        reasons.append("external_html_image")
        sanitized = _EXT_HTML_IMG_RE.sub("[external image removed]", sanitized)
    if _HTML_COMMENT_INJECTION_RE.search(sanitized):
        reasons.append("hidden_html_comment")
        sanitized = _HTML_COMMENT_INJECTION_RE.sub("", sanitized)

    for label, pattern in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            reasons.append(label)
            sanitized = pattern.sub("[QUARANTINED-UNTRUSTED-DIRECTIVE]", sanitized)

    return InjectionScanResult(
        flagged=bool(reasons),
        reasons=list(dict.fromkeys(reasons)),
        sanitized_text=sanitized,
    )


def check_direct_jailbreak(question: str) -> str | None:
    """
    Pre-screen user input for explicit prompt-override or system-prompt extraction attacks.
    Returns a safe refusal reason string when blocked, else None.
    """
    for label, pattern in _INJECTION_PATTERNS:
        if pattern.search(question or ""):
            logger.warning(f"[Guardrail.LLM01] Blocked direct adversarial prompt ({label}).")
            return (
                "I cannot process requests that attempt to override system instructions "
                "or extract internal configuration. Please ask a grounded business or analytics question."
            )
    return None


def _xml_attr(value: object) -> str:
    s = str(value if value is not None else "")
    return (
        s.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def wrap_untrusted_context(
    docs: Iterable[Document],
    *,
    guard_mode: str | None = None,
) -> tuple[str, list[Document], list[str]]:
    """
    Scan retrieved chunks for indirect prompt injection, quarantine/neutralize
    injected instructions, and wrap every chunk inside strict <untrusted_document_context> tags.

    Returns (formatted_context, kept_docs, quarantined_reasons).
    """
    mode = (guard_mode or PROMPT_INJECTION_GUARD_MODE or "filter_and_flag").strip().lower()
    sections: list[str] = []
    kept_docs: list[Document] = []
    flagged_reasons: list[str] = []

    for idx, doc in enumerate(docs, start=1):
        meta = dict(doc.metadata or {})
        scan = scan_text_for_injection(doc.page_content or "")
        if scan.flagged:
            flagged_reasons.extend(scan.reasons)
            logger.warning(
                "[Guardrail.LLM01] Flagged untrusted content in doc_id=%s source=%s reasons=%s",
                meta.get("doc_id"),
                meta.get("source"),
                scan.reasons,
            )
            if mode == "strict":
                continue

        safe_doc = Document(page_content=scan.sanitized_text, metadata=meta)
        kept_docs.append(safe_doc)
        sections.append(
            f'<untrusted_document_context index="{idx}" '
            f'doc_id="{_xml_attr(meta.get("doc_id", ""))}" '
            f'chunk_id="{_xml_attr(meta.get("chunk_id", ""))}" '
            f'source="{_xml_attr(meta.get("source", "unknown"))}" '
            f'page="{_xml_attr(meta.get("page_number", ""))}" '
            f'section="{_xml_attr(meta.get("section_title", ""))}">\n'
            f"{scan.sanitized_text}\n"
            f"</untrusted_document_context>"
        )

    return "\n\n".join(sections), kept_docs, list(dict.fromkeys(flagged_reasons))


def _luhn_valid(digits: str) -> bool:
    if len(digits) < 13 or len(digits) > 19 or not digits.isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def redact_sensitive_output(text: str) -> RedactionResult:
    """
    OWASP LLM02 output filter redacting raw API keys, private keys, JWTs,
    US SSNs, and Luhn-validated payment card numbers, while stripping external image links.
    """
    out = text or ""
    categories: list[str] = []

    if _EXT_MD_IMAGE_RE.search(out):
        out = _EXT_MD_IMAGE_RE.sub("[external image removed]", out)
        categories.append("external_image_exfil")

    for cat, pattern, replacement in _API_KEY_PATTERNS:
        if pattern.search(out):
            out = pattern.sub(replacement, out)
            categories.append(cat)

    if _SSN_RE.search(out):
        out = _SSN_RE.sub("[REDACTED-SSN]", out)
        categories.append("ssn")

    def _replace_card(match: re.Match[str]) -> str:
        raw_match = match.group(0)
        digits = re.sub(r"\D", "", raw_match)
        if _luhn_valid(digits):
            categories.append("payment_card")
            return "[REDACTED-CARD]"
        return raw_match

    out = _CARD_CANDIDATE_RE.sub(_replace_card, out)
    unique_cats = list(dict.fromkeys(categories))
    if unique_cats:
        logger.warning("[Guardrail.LLM02] Redacted sensitive patterns from output: %s", unique_cats)

    return RedactionResult(text=out, redacted=bool(unique_cats), categories=unique_cats)
