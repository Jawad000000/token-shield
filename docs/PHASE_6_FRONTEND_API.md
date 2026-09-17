# Phase 6: Frontend API Contract

## 1. Executive Summary

Phase 6 provides a clean, production-ready backend contract specifically designed for teammate frontend development (React, Next.js, Vite, Vue).

Key capabilities delivered:
1. **Expanded Live Metrics (`GET /metrics/live`)**: Aggregates token savings, cache hit rate, redaction metrics, budget mode distribution, and top strategy rankings.
2. **Session Timeline (`GET /session/{session_id}/timeline`)**: Chronological audit trail powering timeline feeds, receipt drawers, and message badges.
3. **CORS Middleware**: Pre-configured cross-origin resource sharing allowing local development frontends on `:3000` (Next.js/React) and `:5173` (Vite), exposing all `x-tokenshield-*` custom response headers.

---

## 2. API Endpoints

### 2.1 Expanded Live Metrics
**`GET /metrics/live`**

Returns real-time analytics across all logged requests:

```json
{
  "requests": 24,
  "cache_hits": 9,
  "cache_hit_rate": 0.375,
  "raw_input_tokens": 14200,
  "optimized_input_tokens": 6100,
  "upstream_input_tokens": 4800,
  "output_tokens": 3200,
  "saved_tokens": 9400,
  "secrets_redacted": 4,
  "pii_redacted": 3,
  "total_redactions": 7,
  "failovers": 1,
  "notes_deduplicated": 2,
  "turns_shrunk": 5,
  "budget_modes": {
    "normal": 3,
    "saving": 18,
    "critical": 3
  },
  "top_strategies": {
    "guard_mode": 24,
    "conversation_shrinker": 14,
    "exact_cache": 6,
    "semantic_cache": 3,
    "secret_redaction": 4,
    "provider_proxy": 15
  }
}
```

---

### 2.2 Session Timeline
**`GET /session/{session_id}/timeline`**

Returns an ordered chronological list of every turn in a session. Use this to render:
- Chat turn badges (e.g. `Saved 350 tokens`, `EXACT_HIT`).
- Side-panel receipt drawers.
- Redaction indicators (`1 secret protected`).

#### Response Example:
```json
[
  {
    "request_id": "9574c8ee9cc444b98e5a19a5b332b2fc",
    "cache": "EXACT_HIT",
    "provider": "cache",
    "model": "gemini-3.6-flash",
    "raw_input_tokens": 19,
    "optimized_input_tokens": 19,
    "saved_input_tokens": 19,
    "strategies": ["guard_mode", "exact_cache"],
    "secrets_redacted": 0,
    "pii_redacted": 0,
    "guard_mode": "enabled",
    "budget_mode": "saving",
    "created_at": "2026-09-17 15:01:16"
  }
]
```

---

### 2.3 CORS Configuration

TokenShield enables browser-based frontends to interact with the API with full header visibility.

- **Allowed Origins**:
  - `http://localhost:3000` (Next.js / CRA)
  - `http://localhost:5173` (Vite)
  - `http://127.0.0.1:3000`
  - `http://127.0.0.1:5173`
- **Exposed Headers**: `*` (enables frontend JavaScript `fetch()` to read custom `x-tokenshield-*` headers without getting blocked by CORS).

---

## 3. Frontend Integration Snippets

### TypeScript / React Fetch Example:

```typescript
// 1. Send chat completion with session tracking
const response = await fetch("http://127.0.0.1:8000/v1/chat/completions", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-tokenshield-session": "student-demo",
  },
  body: JSON.stringify({
    messages: [{ role: "user", content: "What is binary search?" }],
  }),
});

// Read TokenShield telemetry directly from response headers:
const cacheStatus = response.headers.get("x-tokenshield-cache"); // e.g. "EXACT_HIT"
const savedTokens = response.headers.get("x-tokenshield-saved-input-tokens");
const topic = response.headers.get("x-tokenshield-topic");
const strugglingTopic = response.headers.get("x-tokenshield-struggling-topic");

// 2. Fetch live timeline for receipt drawer:
const timelineRes = await fetch("http://127.0.0.1:8000/session/student-demo/timeline");
const timeline = await timelineRes.json();

// 3. Fetch system-wide savings metrics:
const metricsRes = await fetch("http://127.0.0.1:8000/metrics/live");
const metrics = await metricsRes.json();
```

---

## 4. Verification Evidence

Automated test suite passing:
```powershell
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp -v
```

Output:
```
============================= 34 passed in 2.08s ==============================
```
- `tests/test_metrics.py`:
  - `test_expanded_live_metrics`
  - `test_session_timeline`
  - `test_cors_preflight_headers`
- All 31 existing tests for study mode, caching, guard mode, receipts, and providers.
