# Phase 3: Token Reduction On Every Request

## 1. Executive Summary

In Phase 1 and 2, TokenShield provided:
1. Exact + Semantic Caching (100% token savings on duplicate/similar prompts).
2. Guard Mode (zero secret leaks, PII protection, triple safety guarantees).

However, **cache misses (unique queries)** still passed full conversation history and verbose context to upstream models, costing students tokens and quota.

**Phase 3 solves this problem completely.** Even on a cache `MISS`, TokenShield actively optimizes and shrinks the prompt *before* forwarding it upstream, saving **30% to 70% of input tokens and drastically cutting output token generation**.

---

## 2. The Phase 3 Architecture Pipeline

When a request arrives at `POST /v1/chat/completions`:

```mermaid
flowchart TD
    A[Incoming Chat Request] --> B[Phase 2: Guard Mode Redaction]
    B --> C{Cache Check: Exact / Semantic}
    C -- HIT --> D[Return Cached Answer: 100% Saved]
    C -- MISS --> E[Phase 3 Pipeline]
    
    subgraph Phase 3 Optimization Engine
        E --> F[Step 1: Session Note Deduplication (app/memory.py)]
        F --> G[Step 2: Conversation History Shrinker (app/shrinker.py)]
        G --> H[Step 3: Answer Budget Injection (app/budgeter.py)]
    end

    H --> I[Sanitized & Compact Upstream Payload]
    I --> J[Provider Waterfall: Vercel -> Google -> Ollama -> Kilo]
    J --> K[Concise LLM Response]
    K --> L[Receipt Logging & Response Headers with Saved Tokens]
```

---

## 3. Core Modules Explained

### 3.1 Answer Budget Directives (`app/budgeter.py`)
Controls verbosity and output token generation from the upstream LLM:

| Budget Mode | Header Value | Behavior & Directive Injected |
| :--- | :--- | :--- |
| **Normal** | `normal` | Default model behavior; standard answers. |
| **Saving** (Default) | `saving` | Injects concise directive: at most 4 bullets or 1 brief paragraph, at most 1 minimal code snippet. Drops pleasantries and prompt echoing. |
| **Critical** | `critical` | Injects ultra-compact directive: strictly under 60 words, hint-first, zero filler. |

**Auto-Escalation**:
- If `raw_input_tokens >= 4000`: Automatically escalates to `critical` to protect remaining quota.
- If `raw_input_tokens >= 2000` and mode is `normal`: Automatically escalates to `saving`.

---

### 3.2 In-Session Note Deduplication (`app/memory.py`)
Students frequently paste long lecture slides, syllabi, codebases, or textbook excerpts repeatedly across multiple questions in the same chat session.
- TokenShield tracks chunks larger than **180 characters** per session ID.
- The first time a note appears, it is stored in an in-memory session index keyed by its SHA-256 hash.
- On subsequent questions in that same session containing identical chunks, TokenShield replaces the redundant chunk with a compact reference tag:
  `[Reference: note_a1b2c3d4]`
- This saves hundreds or thousands of redundant input tokens per query.

---

### 3.3 Conversation History Shrinker (`app/shrinker.py`)
Multi-turn conversations quickly bloat prompt size because OpenAI-compatible chat formats require sending all previous turns.
- **Rule 1 — Latest Question Preserved**: The final user prompt is preserved **100% intact and unedited**.
- **Rule 2 — History Compression**: When conversation length exceeds 2 messages:
  - System instructions are merged into a single `[System Instructions]` block.
  - Previous turns are compressed into compact, one-line summaries (`User: ...`, `AI: ...`), dropping intermediate `<thought>` tags, verbose code snippets, and conversational filler.
  - The budget directive is appended to the consolidated system prompt.
- Result: Upstream models receive a 2-message context: `[Consolidated Context Block, Latest User Prompt]`, cutting previous turn tokens by up to 70%.

---

### 3.4 Context-Fingerprinted Semantic Caching (`app/cache.py`)
Generic follow-ups like `"Why?"`, `"Give me an example"`, or `"Explain that again"` lack standalone topic context.
- For single-turn prompts, TokenShield caches globally across all sessions using the question text.
- For multi-turn follow-ups, `build_cache_query` prepends a compact context fingerprint of the prior turns (e.g. `[Context: user: Explain Quicksort | assistant: Quicksort divides...] Question: Why?`).
- This guarantees that a follow-up `"Why?"` in computer science will **never** collide with a follow-up `"Why?"` in biology or history.

---

### 3.5 Token Inflation Safeguard
If a conversation is so brief that appending a budget directive would cause `optimized_input_tokens > raw_input_tokens`:
- TokenShield automatically reverts to the original sanitized messages.
- Sets `optimized_input_tokens = raw_input_tokens`, `saved_input_tokens = 0`, `turns_shrunk = 0`, and records strategy `optimization_reverted_no_savings`.
- **Guarantee**: Students are **never charged extra input tokens** by the proxy.

---

## 4. Deterministic Response Headers (Phase 3)

TokenShield returns consistent headers on **every single request**:

```http
x-tokenshield-cache: MISS
x-tokenshield-provider: google
x-tokenshield-budget-mode: saving
x-tokenshield-turns-shrunk: 2
x-tokenshield-notes-deduplicated: 1
x-tokenshield-raw-input-tokens: 266
x-tokenshield-optimized-input-tokens: 133
x-tokenshield-upstream-input-tokens: 133
x-tokenshield-saved-input-tokens: 133
x-tokenshield-strategies: guard_mode,note_deduplication,conversation_shrinker,budget_saving,provider_proxy,provider_waterfall
x-tokenshield-request-id: 2614193386514646ab9b559127e18855
```

---

## 5. Token Accounting Formula

| Metric | On Cache HIT | On Cache MISS (Unique Query) |
| :--- | :--- | :--- |
| `raw_input_tokens` | `estimate_message_tokens(original_messages)` | `estimate_message_tokens(original_messages)` |
| `optimized_input_tokens` | `raw_input_tokens` (served immediately from cache) | `estimate_message_tokens(optimized_messages)` |
| `upstream_input_tokens` | `0` (no upstream provider called) | `optimized_input_tokens` |
| `saved_input_tokens` | `raw_input_tokens` (100% saved) | `max(0, raw_input_tokens - optimized_input_tokens)` |
| `output_tokens` | Cached answer token count | Actual generated answer token count |

---

## 6. How to Test Manually

### PowerShell Test (Multi-Turn Token Reduction)
```powershell
$body = @{
  messages = @(
    @{ role = "user"; content = "What is quicksort in 50 words?" },
    @{ role = "assistant"; content = "Quicksort is a divide-and-conquer algorithm that selects a pivot and partitions the array into two sub-arrays according to whether they are less than or greater than the pivot. It then sorts the sub-arrays recursively. Average time complexity is O(n log n), while worst-case is O(n^2)." },
    @{ role = "user"; content = "What is its best-case time complexity in 5 words?" }
  )
} | ConvertTo-Json -Depth 5

$res = Invoke-WebRequest http://127.0.0.1:8000/v1/chat/completions `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{
    "x-tokenshield-session" = "student-algo-session";
    "x-tokenshield-budget-mode" = "saving"
  } `
  -Body $body

# 1. View model response
($res.Content | ConvertFrom-Json).choices[0].message.content

# 2. View TokenShield savings headers
$res.Headers["x-tokenshield-cache"]
$res.Headers["x-tokenshield-turns-shrunk"]
$res.Headers["x-tokenshield-raw-input-tokens"]
$res.Headers["x-tokenshield-optimized-input-tokens"]
$res.Headers["x-tokenshield-saved-input-tokens"]
$res.Headers["x-tokenshield-strategies"]
```

### Inspect the Audit Receipt
```powershell
$reqId = $res.Headers["x-tokenshield-request-id"]
Invoke-RestMethod "http://127.0.0.1:8000/receipt/$reqId"
```

### Run the Automated Test Suite
```powershell
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp
```
*Expected: 22 passed.*

---

## 7. Phase 3.2 Hardening (Post-Review Fixes)

The following reliability and security hardening was applied after initial Phase 3 completion:

### Bug Fixes
| Fix | File | Details |
| :--- | :--- | :--- |
| Missing `from typing import Any` import | `app/cache.py` | Would crash at runtime if type hints were resolved (e.g. by Pydantic or doc generators). |
| Misplaced `import re` in middle of file | `app/shrinker.py` | Moved to top-level imports where it belongs. |

### Security & Reliability
| Fix | File | Details |
| :--- | :--- | :--- |
| Reuse `httpx.AsyncClient` | `app/providers.py` | One shared connection pool instead of creating/destroying a TCP+TLS connection per request. Prevents socket exhaustion under load. |
| Message count limit (`MAX_MESSAGES = 50`) | `app/main.py` | Prevents DoS via oversized payloads that would CPU-block on regex scanning, embedding, and cache lookup. |
| SQLite WAL mode | `app/db.py` | `PRAGMA journal_mode=WAL` enables safer concurrent read/write access. |

### Performance & Memory
| Fix | File | Details |
| :--- | :--- | :--- |
| Cached tiktoken encoder | `app/tokens.py` | Module-level singleton instead of re-importing and re-initializing on every call. |
| Session memory LRU eviction | `app/memory.py` | `MAX_SESSIONS = 100` — evicts oldest session when capacity is reached, preventing unbounded memory growth. |
| Removed dead code | `app/main.py` | `latest_user_text()` was replaced by `build_cache_query()` but never deleted. |

