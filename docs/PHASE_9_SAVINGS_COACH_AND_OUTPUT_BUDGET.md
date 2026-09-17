# Phase 9: Savings Coach, Output Budget Cap & Student Cost Forecast

## Overview
Phase 9 transitions TokenShield from a passive token optimization proxy into an active **Educational Savings Coach**. Instead of merely displaying numeric token reductions, TokenShield inspects every interaction and coaches students on how to formulate cheaper prompts, avoid verbose responses, utilize Hint/Critical modes, iterate on code via diffs, and preserve their daily free quota.

---

## Key Components

### 1. Hard Output Budget Capping (`app/budgeter.py`)
Token generation accounts for a significant portion of LLM costs and response latency. While system prompt directives guide the model, upstream providers can still produce verbose responses without parameter-level bounds.

TokenShield enforces hard parameter-level `max_tokens` upstream according to the active budget mode:
* **`normal`**: 700 max output tokens (Standard, comprehensive explanations).
* **`saving`**: 300 max output tokens (Direct, concise answers).
* **`critical`**: 120 max output tokens (Hint-first, ultra-compact answers).

If the client specifies a lower `max_tokens`, TokenShield preserves the smaller value (`min(client_max, mode_cap)`).

#### Output Savings Measurement
TokenShield measures output savings against the standard unconstrained 700-token baseline:
$$\text{Output Tokens Saved} = \max(0, 700 - \text{actual\_output\_tokens}) \quad (\text{if mode} \neq \text{"normal"})$$

---

### 2. Savings Coach Engine (`app/recommendations.py`)
TokenShield inspects the completed request receipt across 7 dynamic coaching triggers to generate practical, actionable tips:

| Trigger | Category | Recommendation / Advice |
| :--- | :--- | :--- |
| **Cache Hit (HIT / EXACT_HIT / SOFT_HIT)** | `cache` | Celebrates 0 upstream API token consumption and instant latency. |
| **High Output (>250 tokens or `normal` mode)** | `output_budget` | Advises switching to Hint/Critical mode to cut ~60% of output tokens. |
| **Critical Mode Active** | `output_budget` | Acknowledges active hint mode and highlights output tokens saved. |
| **Student Struggling / Weak Topic** | `study` | Suggests generating a 5-minute revision pack & active recall quiz. |
| **Repeated Notes Compressed** | `notes` | Explains that repetitive lecture notes were replaced by tag pointers. |
| **Code AST Diff Pruned** | `code` | Notifies student that only code diffs were sent upstream. |
| **Provider Failover Shield** | `failover` | Reassures student that downtime / rate limits were bypassed. |
| **Long Uncompressed Prompt** | `prompt` | Suggests asking for bullet points or uploading notes once. |

---

### 3. Student Cost Forecast & Quota Runway (`app/db.py`)
Extends `GET /metrics/live` with predictive student quota metrics:
```json
{
  "forecast": {
    "daily_token_quota": 50000,
    "used_tokens": 1240,
    "remaining_quota": 48760,
    "estimated_questions_left": 139,
    "projected_daily_tokens": 1736,
    "budget_mode_recommendation": "saving",
    "runway_hours": 13.9,
    "runway_message": "At current pace, free quota lasts ~13.9 hours. Switch to Critical Mode to extend to ~30.9 hours."
  }
}
```

---

### 4. HTTP Headers Added
* `x-tokenshield-max-output-tokens`: Max output cap enforced upstream (e.g. `120`, `300`, `700`).
* `x-tokenshield-saved-output-tokens`: Estimated output tokens saved vs 700 baseline.
* `x-tokenshield-recommendations-count`: Total number of recommendations generated for the student.

---

## Verification & Testing
Run automated unit and integration tests:
```bash
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp tests/test_recommendations.py -v
```
Run the full test suite:
```bash
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp -v
```
