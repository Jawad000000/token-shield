# Phase 7: Provider Waterfall Polish

## 1. Executive Summary

Phase 7 hardens and clarifies TokenShield's multi-provider waterfall routing mechanism. In student environments where free-tier keys frequently encounter rate limits (`429`), billing halts (`402`), or permission issues (`403`), TokenShield transparently waterfalls to the next healthy provider while recording the exact attempt path.

Key capabilities delivered:
1. **Provider Status Endpoint (`GET /providers/status`)**: Exposes the configured availability and active model for all waterfall providers without leaking API keys or secrets.
2. **Granular Attempt Tracking (`provider_attempts`)**: Logs each attempted provider in chronological order alongside its HTTP status code (e.g. `403`, `429`, `200`).
3. **Receipt & Timeline Integration**: Full persistence and propagation through `request_logs`, `/receipt/{request_id}`, and `/session/{session_id}/timeline` enabling frontends to display user-friendly status toasts like:
   > *"Vercel hit rate limit (429) → seamlessly switched to Google Gemini 2.5 (200)"*

---

## 2. Endpoints & Schemas

### 2.1 Provider Status
**`GET /providers/status`**

Returns the operational status of all waterfall providers in order of execution priority:

```json
[
  {
    "name": "vercel",
    "configured": true,
    "model": "meta-llama/llama-3.3-70b-instruct"
  },
  {
    "name": "google",
    "configured": true,
    "model": "gemini-2.5-flash"
  },
  {
    "name": "groq",
    "configured": false,
    "model": "llama-3.3-70b-versatile"
  },
  {
    "name": "cohere",
    "configured": true,
    "model": "command-r-plus"
  }
]
```

> **Security Note**: This endpoint strictly outputs `name`, `configured`, and `model`. `api_key` and upstream credentials are never returned.

---

### 2.2 Attempt Tracking in Receipts & Timelines

When a request reaches upstream providers on a cache `MISS`, TokenShield executes providers sequentially until one succeeds. Each step is logged in `provider_attempts`:

#### Direct Success (No Failover)
```json
"provider_attempts": [
  {
    "provider": "vercel",
    "status": 200
  }
]
```

#### Multi-Step Failover
```json
"provider_attempts": [
  {
    "provider": "vercel",
    "status": 403
  },
  {
    "provider": "google",
    "status": 429
  },
  {
    "provider": "cohere",
    "status": 200
  }
]
```

#### Cache Hits
For requests fulfilled by `EXACT_HIT` or `HIT`, no upstream providers are contacted:
```json
"provider_attempts": []
```

---

## 3. Frontend Integration Guide

Frontends can consume `provider_attempts` from:
1. Response body payload: `res.data.tokenshield.provider_attempts`
2. Receipt endpoint: `GET /receipt/{request_id}`
3. Session timeline: `GET /session/{session_id}/timeline`

### Sample UI Toast Component (React)

```tsx
interface ProviderAttempt {
  provider: string;
  status: number;
}

export function WaterfallBadge({ attempts }: { attempts: ProviderAttempt[] }) {
  if (!attempts || attempts.length <= 1) return null;

  const fails = attempts.filter(a => a.status !== 200);
  const success = attempts.find(a => a.status === 200);

  return (
    <div className="waterfall-notice flex items-center gap-1.5 text-xs text-amber-600 bg-amber-50 px-2.5 py-1 rounded-full border border-amber-200">
      <span className="font-semibold">⚡ Auto-Failover:</span>
      {fails.map((f, i) => (
        <span key={i} className="line-through text-red-500">
          {f.provider} ({f.status})
        </span>
      ))}
      <span>→</span>
      <span className="text-green-700 font-medium">{success?.provider}</span>
    </div>
  );
}
```

---

## 4. Verification

Run automated test suite:
```powershell
python -m pytest tests/test_providers.py -v
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp -v
```
