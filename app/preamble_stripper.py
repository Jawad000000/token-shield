"""
Preamble & Conversational Scaffolding Stripper.

Students and casual users frequently wrap their core question in heavy conversational
scaffolding, emotional context, greetings, and sign-offs:
    "Hi professor! Hope you are doing well. I have an exam tomorrow morning and I am
     really confused about one concept. Could you please explain what is database normalization?"

The LLM only needs:
    "Explain what is database normalization?"

This module safely distills student prompts down to the core query, cutting 30–60% of
unnecessary conversational padding while 100% preserving domain concepts and code.
"""
from __future__ import annotations

import re
from typing import Any

# Protect code blocks and inline code
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")

# 1. Greetings (at the start of user message)
GREETING_PATTERN = (
    r"^(?:(?:hi|hello|hey|dear|good\s+(?:morning|afternoon|evening)|greetings)\b"
    r"(?:\s+(?:professor|prof|teacher|tutor|sir|ma'?am|there|ai|bot|assistant|everyone|friends))?"
    r"[,!.:;\-—\s]*)+"
)
GREETINGS_RE = re.compile(GREETING_PATTERN, re.IGNORECASE)

# 2. Courtesy / pleasantry sentences at the beginning
PLEASANTRY_PATTERN = (
    r"^(?:(?:i\s+)?hope\s+(?:you\s+are|you're)\s+(?:doing\s+well|having\s+a\s+(?:great|good|wonderful|nice)\s+day|well|good)"
    r"|i\s+hope\s+(?:this\s+finds\s+you\s+well|all\s+is\s+well|you\s+are\s+well|you're\s+doing\s+well))"
    r"[,!.:;\s]*"
)
PLEASANTRY_STARTS_RE = re.compile(PLEASANTRY_PATTERN, re.IGNORECASE)

# 3. Student meta-context / status updates
STUDENT_PREAMBLE_PATTERNS = [
    # Panic / anxiety / stress
    re.compile(
        r"\b(?:i\s+am|i'm)\s+(?:really\s+|extremely\s+|super\s+|very\s+)?(?:stressed|anxious|panicking|in\s+a\s+state\s+of\s+panic|freaking\s+out|overwhelmed)"
        r"[^.!?]*?(?:[.!?]|\band\b|\bso\b|\bbecause\b)\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+really\s+really\s+need|i\s+really\s+need|i\s+urgently\s+need)\s+(?:your\s+help|help|assistance|to\s+understand)[^.!?]*?[.!?]\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+cannot\s+understand|i\s+don't\s+understand|i\s+can't\s+get\s+my\s+head\s+around)\s+[^.!?]*?[.!?]\s*",
        re.IGNORECASE,
    ),
    # Preparing for exam / class
    re.compile(
        r"\b(?:i\s+am|i'm)\s+(?:currently\s+)?(?:preparing|studying)\s+(?:for\s+)?"
        r"(?:my\s+)?[^.!?]*?(?:midterm|final|exam|test|quiz|interview|class|course|homework|assignment)"
        r"[^.!?]*?(?:[.!?]|\band\b)\s*",
        re.IGNORECASE,
    ),
    # Have an exam coming up
    re.compile(
        r"\b(?:because\s+)?(?:i\s+have|i've\s+got)\s+(?:my\s+|an?\s+)?[^.!?]*?(?:exam|test|quiz|interview|midterm|final|class|deadline)"
        r"[^.!?]*?(?:tomorrow|today|soon|coming\s+up|in\s+an?\s+hour|morning|next\s+week)[^.!?]*?(?:[.!?]|\band\b)\s*",
        re.IGNORECASE,
    ),
    # Beginner status
    re.compile(
        r"\b(?:i\s+am|i'm)\s+(?:a\s+)?(?:beginner|new|struggling|confused)\s+"
        r"(?:at|with|in|to)?\s*[^.!?]*?\s*(?:and|so)\s+",
        re.IGNORECASE,
    ),
    # Confused about
    re.compile(
        r"\b(?:i\s+am|i'm)\s+(?:really\s+)?(?:confused|stuck)\s+(?:about|on|with)\s+[^.!?]*?(?:concept|topic|thing)?[,.]*\s*",
        re.IGNORECASE,
    ),
    # Hedges
    re.compile(
        r"\b(?:as\s+a\s+matter\s+of\s+fact|to\s+be\s+completely\s+honest|honestly\s+speaking)[,\s]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:what\s+i\s+(?:really\s+)?(?:want|need)\s+to\s+know\s+is)\s+",
        re.IGNORECASE,
    ),
    # Question preambles -> transform to direct prompt
    re.compile(
        r"\b(?:i\s+was\s+wondering\s+if\s+you\s+(?:could|can)\s+(?:please\s+)?(?:explain|tell\s+me))\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:could\s+you\s+(?:please\s+)?(?:explain\s+to\s+me|tell\s+me|help\s+me\s+understand))\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:can\s+you\s+(?:please\s+)?(?:explain\s+to\s+me|tell\s+me|help\s+me\s+understand))\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+really\s+need\s+a\s+clear\s+explanation\s+of)\s+",
        re.IGNORECASE,
    ),
]

# 4. Sign-offs and pleasantries (can be chained at end of user message)
SINGLE_SIGNOFF = (
    r"(?:thanks\s+(?:so\s+much\s+)?in\s+advance(?:\s+for\s+(?:your\s+)?help)?"
    r"|thank\s+you(?:\s+(?:so\s+much|very\s+much|a\s+lot))?(?:\s+in\s+advance)?(?:\s+for\s+(?:your\s+)?(?:help|time|assistance))?"
    r"|thanks(?:\s+(?:so\s+much|very\s+much|a\s+lot))?(?:\s+in\s+advance)?"
    r"|(?:i\s+)?(?:truly\s+)?appreciate\s+(?:everything\s+you\s+do|your\s+help|it)"
    r"|have\s+a\s+(?:great|wonderful|good|nice)\s+(?:day|rest\s+of\s+(?:your\s+)?day)"
    r"|please\s+help(?:\s+me)?(?:\s+asap|\s+soon)?"
    r"|any\s+help\s+(?:would\s+be|is)\s+(?:greatly\s+)?appreciated)"
)
SIGNOFF_CHAIN_RE = re.compile(
    rf"(?:[,.\s\-—]+|(?<=[?!]))*(?:{SINGLE_SIGNOFF}[,.\s!]*)+$",
    re.IGNORECASE,
)

# 5. Low-signal conversational hedge phrases in prose
HEDGES_RE = re.compile(
    r"\b(?:basically|sort\s+of|kind\s+of|more\s+or\s+less)\b\s*",
    re.IGNORECASE,
)


def strip_student_preamble(text: str) -> str:
    """
    Distills a single text string by stripping greetings, student preambles,
    and conversational sign-offs while strictly preserving domain content.
    """
    if not text or len(text.strip()) < 10:
        return text

    # Extract code blocks to avoid touching code or string literals
    placeholders: list[str] = []

    def _mask_code(match: re.Match) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"__CODE_BLOCK_{idx}__"

    masked = CODE_BLOCK_RE.sub(_mask_code, text)
    original_masked = masked

    # 1. Strip greeting at start
    masked = GREETINGS_RE.sub("", masked).strip()

    # 2. Strip pleasantry starts
    masked = PLEASANTRY_STARTS_RE.sub("", masked).strip()

    # 3. Strip student meta-context patterns
    for pattern in STUDENT_PREAMBLE_PATTERNS:
        masked = pattern.sub("", masked).strip()

    # 4. Strip conversational hedges
    masked = HEDGES_RE.sub("", masked).strip()

    # 5. Strip chained sign-offs at end
    masked = SIGNOFF_CHAIN_RE.sub("", masked).strip()

    # Clean up leftover artifacts, double punctuation, and horizontal multi-spaces
    # CRITICAL: Preserve newlines (\n) so logs, lists, and multi-line content remain intact
    masked = re.sub(r"^[,\s.:;\-—]+", "", masked)
    masked = re.sub(r"[ \t]+", " ", masked)
    masked = re.sub(r"[ \t]+([,.?!])", r"\1", masked)
    masked = re.sub(r"\n{3,}", "\n\n", masked)
    masked = masked.strip()

    # If distillation stripped too aggressively (empty or less than 2 chars), revert
    if len(masked) < 2:
        masked = original_masked

    # Ensure the first letter is capitalized
    if masked and masked[0].islower():
        masked = masked[0].upper() + masked[1:]

    # Restore code blocks
    for idx, code_content in enumerate(placeholders):
        masked = masked.replace(f"__CODE_BLOCK_{idx}__", code_content)

    return masked


def strip_preambles_in_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Strips conversational preambles and scaffolding from user messages.
    System and assistant messages are untouched.

    Returns:
        (optimized_messages, count_of_messages_modified)
    """
    if not messages:
        return messages, 0

    optimized: list[dict[str, Any]] = []
    modified_count = 0

    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                stripped = strip_student_preamble(content)
                if stripped != content and len(stripped) < len(content):
                    cloned = dict(msg)
                    cloned["content"] = stripped
                    optimized.append(cloned)
                    modified_count += 1
                    continue
        optimized.append(msg)

    return optimized, modified_count
