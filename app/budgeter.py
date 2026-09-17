from __future__ import annotations

import os

BUDGET_DIRECTIVES = {
    "saving": (
        "[Answer Budget: SAVING]\n"
        "Lead with the direct answer in the first sentence. Crisp code if relevant. Zero preamble, zero filler."
    ),
    "critical": (
        "[Answer Budget: CRITICAL]\n"
        "Ultra-compact hint-first response strictly under 60 words. "
        "Provide only the essential insight or minimal correction. Zero filler, zero pleasantries."
    ),
}


def resolve_budget_mode(requested_mode: str | None = None, raw_tokens: int = 0) -> str:
    default_mode = os.getenv("TOKENSHIELD_DEFAULT_BUDGET_MODE", "normal").lower()
    mode = (requested_mode or default_mode).lower().strip()

    if mode not in {"normal", "saving", "critical"}:
        mode = "normal"

    # Auto-escalation based on token load
    if raw_tokens >= 4000:
        return "critical"
    if raw_tokens >= 2000 and mode == "normal":
        return "saving"

    return mode


def get_budget_directive(requested_mode: str | None = None, raw_tokens: int = 0) -> tuple[str, str]:
    mode = resolve_budget_mode(requested_mode, raw_tokens)
    directive = BUDGET_DIRECTIVES.get(mode, "")
    return directive, mode


BUDGET_MAX_OUTPUT_TOKENS = {
    "normal": 700,
    "saving": 300,
    "critical": 120,
}


def get_budget_output_cap(mode: str) -> int:
    """Returns the maximum output token cap for the given budget mode."""
    return BUDGET_MAX_OUTPUT_TOKENS.get(mode.lower().strip(), 300)


def estimate_output_tokens_saved(mode: str, actual_output_tokens: int) -> int:
    """Estimates output tokens saved compared to the unconstrained 700-token normal baseline."""
    if mode.lower().strip() == "normal":
        return 0
    baseline = BUDGET_MAX_OUTPUT_TOKENS["normal"]
    return max(0, baseline - actual_output_tokens)
