from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GuardResult:
    secrets_redacted: int = 0
    pii_redacted: int = 0
    guard_mode: str = "enabled"

    @property
    def total_redactions(self) -> int:
        return self.secrets_redacted + self.pii_redacted

    @property
    def applied(self) -> bool:
        return self.total_redactions > 0


SECRET_PATTERNS = [
    re.compile(r"\bvck_[A-Za-z0-9_]{25,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9-_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9\-_.~+/]{20,}\b", re.IGNORECASE),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9-_]{16,})['\"]?"),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def redact_text(text: str) -> tuple[str, int, int]:
    if not text:
        return text, 0, 0

    secrets_count = 0
    pii_count = 0

    # 1. Redact Secrets
    for pattern in SECRET_PATTERNS:
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        # Process replacements in reverse order to preserve string offsets
        for match in reversed(matches):
            secrets_count += 1
            start, end = match.span()
            placeholder = f"[REDACTED_SECRET_{secrets_count}]"
            # If pattern captured group 1 (e.g. key=secret), only replace secret part
            if match.groups() and match.group(1):
                g_start, g_end = match.span(1)
                text = text[:g_start] + placeholder + text[g_end:]
            else:
                text = text[:start] + placeholder + text[end:]

    # 2. Redact Emails
    email_matches = list(EMAIL_PATTERN.finditer(text))
    for match in reversed(email_matches):
        pii_count += 1
        start, end = match.span()
        text = text[:start] + f"[REDACTED_EMAIL_{pii_count}]" + text[end:]

    # 3. Redact Phone Numbers
    phone_count = 0
    phone_matches = list(PHONE_PATTERN.finditer(text))
    for match in reversed(phone_matches):
        matched_str = match.group(0)
        if "[" in matched_str or "]" in matched_str:
            continue
        phone_count += 1
        pii_count += 1
        start, end = match.span()
        text = text[:start] + f"[REDACTED_PHONE_{phone_count}]" + text[end:]

    return text, secrets_count, pii_count


def redact_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], GuardResult]:
    sanitized: list[dict[str, Any]] = []
    total_secrets = 0
    total_pii = 0

    for msg in messages:
        cloned_msg = dict(msg)
        content = cloned_msg.get("content")

        if isinstance(content, str):
            clean_text, sec_c, pii_c = redact_text(content)
            cloned_msg["content"] = clean_text
            total_secrets += sec_c
            total_pii += pii_c
        elif isinstance(content, list):
            new_content: list[Any] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    clean_text, sec_c, pii_c = redact_text(item["text"])
                    cloned_item = dict(item)
                    cloned_item["text"] = clean_text
                    new_content.append(cloned_item)
                    total_secrets += sec_c
                    total_pii += pii_c
                else:
                    new_content.append(copy.deepcopy(item) if isinstance(item, (dict, list)) else item)
            cloned_msg["content"] = new_content

        sanitized.append(cloned_msg)

    return sanitized, GuardResult(secrets_redacted=total_secrets, pii_redacted=total_pii)
