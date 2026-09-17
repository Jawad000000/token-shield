from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import ProviderConfig
from app.providers import ProviderRouter

VERIFIER_SYSTEM_PROMPT = (
    "You are a strict cache validator. You reply with exactly one word: YES or NO. Nothing else."
)

VERIFIER_USER_TEMPLATE = (
    "A user asked a NEW question. Below is an answer that was cached for a DIFFERENT but similar question.\n\n"
    "NEW QUESTION:\n{question}\n\n"
    "CACHED ANSWER:\n{answer}\n\n"
    "Does the cached answer fully and correctly answer the new question, with nothing important "
    "missing, contradicted, or about the wrong subject? Reply YES or NO."
)

MAX_QUESTION_CHARS = 600
MAX_ANSWER_CHARS = 1200
VERIFIER_MAX_TOKENS = 4


@dataclass(frozen=True)
class VerificationResult:
    """
    Outcome of validating a SOFT_HIT before it is served from cache.

    verdict:
      "accept"      -> cached answer genuinely answers the new question, serve it
      "reject"      -> cached answer does not fit, fall through to a real upstream call
      "unavailable" -> no verifier provider configured or the check failed; fail open (serve)
    """

    verdict: str = "unavailable"
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    reason: str = ""

    @property
    def rejected(self) -> bool:
        return self.verdict == "reject"

    def as_receipt(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "provider": self.provider,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "reason": self.reason,
        }


def _first_text(payload: dict[str, Any]) -> str:
    try:
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _tokens_used(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if total:
            return int(total)
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        if prompt or completion:
            return prompt + completion
    return 0


class SoftHitVerifier:
    """
    Spends a handful of tokens on the cheapest configured provider to confirm that a
    borderline semantic cache match (SOFT_HIT) actually answers the user's question.

    This converts the riskiest part of the cache -- serving a 0.90-similar stranger's
    answer -- into a checked decision, while still avoiding a full generation.
    """

    def __init__(
        self,
        providers: tuple[ProviderConfig, ...] = (),
        *,
        enabled: bool = True,
        router: ProviderRouter | None = None,
    ) -> None:
        self.providers = tuple(providers)
        self.enabled = enabled
        self._router = router

    def cheapest_provider(self) -> ProviderConfig | None:
        """Last configured provider in the waterfall is the cheapest fallback tier."""
        configured = [provider for provider in self.providers if provider.configured]
        return configured[-1] if configured else None

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._router is not None:
            return True
        return self.cheapest_provider() is not None

    async def verify(self, question: str, answer: str) -> VerificationResult:
        if not self.enabled:
            return VerificationResult(verdict="unavailable", reason="disabled")

        provider = self.cheapest_provider()
        if self._router is None and provider is None:
            return VerificationResult(verdict="unavailable", reason="no_provider_configured")

        router = self._router or ProviderRouter((provider,))
        model = provider.model if provider else "verifier"

        payload = {
            "model": model,
            "max_tokens": VERIFIER_MAX_TOKENS,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": VERIFIER_USER_TEMPLATE.format(
                        question=question[:MAX_QUESTION_CHARS],
                        answer=answer[:MAX_ANSWER_CHARS],
                    ),
                },
            ],
        }

        try:
            result = await router.chat_completion(payload)
            response, used_provider = result[0], result[1]
        except Exception as error:  # noqa: BLE001 - verification must never break the request
            return VerificationResult(verdict="unavailable", reason=f"error:{type(error).__name__}")

        text = _first_text(response).upper()
        provider_name = getattr(used_provider, "name", "verifier")
        provider_model = getattr(used_provider, "model", model)
        tokens = _tokens_used(response)

        if text.startswith("YES"):
            verdict = "accept"
        elif text.startswith("NO"):
            verdict = "reject"
        else:
            # Unparseable verdict: fail open rather than block a legitimate cache hit.
            verdict = "unavailable"

        return VerificationResult(
            verdict=verdict,
            provider=provider_name,
            model=provider_model,
            tokens_used=tokens,
            reason="verified" if verdict != "unavailable" else "unparseable_verdict",
        )
