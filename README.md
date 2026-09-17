# TokenShield

Local FastAPI proxy for reducing LLM token spend with semantic caching, provider fallback, and live usage metrics.

## Quickstart for Teammates

### 1. Clone & Install
```bash
git clone https://github.com/Jawad000000/token-shield.git
cd token-shield

# Create and activate virtual environment (optional but recommended)
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment
```bash
# On Windows:
copy .env.example .env.local
# On macOS/Linux:
cp .env.example .env.local
```
Add your provider API keys (Google, Groq, Vercel, etc.) inside `.env.local`.

### 3. Run Server
```bash
python -m uvicorn app.main:app --reload
```

### 4. Run Test Suite (48 Tests Passing)
```bash
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp -v
```

## Secret Setup

Do not paste API keys into chat or commit them. Add keys locally in `.env.local`:

```env
AI_GATEWAY_API_KEY=your_vercel_ai_gateway_key
GOOGLE_API_KEY=your_google_ai_key
GROQ_API_KEY=your_groq_key
```

`.env.local` is ignored by Git.

For many fallback keys, use numbered provider entries. Providers are tried in numeric order, and each `API_KEY_ENV` names the environment variable containing the secret:

```env
TOKENSHIELD_PROVIDER_1_NAME=vercel
TOKENSHIELD_PROVIDER_1_BASE_URL=https://ai-gateway.vercel.sh/v1
TOKENSHIELD_PROVIDER_1_API_KEY_ENV=AI_GATEWAY_API_KEY
TOKENSHIELD_PROVIDER_1_MODEL=openai/gpt-5.5

TOKENSHIELD_PROVIDER_2_NAME=google
TOKENSHIELD_PROVIDER_2_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
TOKENSHIELD_PROVIDER_2_API_KEY_ENV=GOOGLE_API_KEY
TOKENSHIELD_PROVIDER_2_MODEL=gemini-2.5-flash

TOKENSHIELD_PROVIDER_3_NAME=groq
TOKENSHIELD_PROVIDER_3_BASE_URL=https://api.groq.com/openai/v1
TOKENSHIELD_PROVIDER_3_API_KEY_ENV=GROQ_API_KEY
TOKENSHIELD_PROVIDER_3_MODEL=llama-3.1-8b-instant
```

To use multiple keys for the same upstream, repeat the provider with a different key env var:

```env
VERCEL_KEY_1=...
VERCEL_KEY_2=...

TOKENSHIELD_PROVIDER_1_NAME=vercel-a
TOKENSHIELD_PROVIDER_1_BASE_URL=https://ai-gateway.vercel.sh/v1
TOKENSHIELD_PROVIDER_1_API_KEY_ENV=VERCEL_KEY_1
TOKENSHIELD_PROVIDER_1_MODEL=openai/gpt-5.5

TOKENSHIELD_PROVIDER_2_NAME=vercel-b
TOKENSHIELD_PROVIDER_2_BASE_URL=https://ai-gateway.vercel.sh/v1
TOKENSHIELD_PROVIDER_2_API_KEY_ENV=VERCEL_KEY_2
TOKENSHIELD_PROVIDER_2_MODEL=openai/gpt-5.5
```

## Caching & Optimization

TokenShield employs a multi-tier cache to maximize token savings:

1. **Exact Cache (`EXACT_HIT`)**: Normalized SHA-256 hash lookup (`O(1)`). Identical queries hit instantly without embedding or vector math.
2. **Semantic Cache (`HIT`)**: Cosine similarity $\ge$ `0.95` (configurable via `TOKENSHIELD_CACHE_HARD_THRESHOLD`). Rephrased queries return cached response with zero upstream tokens.
3. **Soft Hit (`SOFT_HIT`)**: Cosine similarity between `0.90` and `0.95` (configurable via `TOKENSHIELD_CACHE_SOFT_THRESHOLD`). High confidence semantic match.
4. **Cache Miss (`MISS`)**: Executes unique query token reduction pipeline (Guard Mode redaction, session note deduplication, and conversation shrinker/budgeter) before calling upstream provider.

### Embedding Backend

By default, TokenShield uses a fast, deterministic, zero-dependency 384-dimensional hash embedding backend (`hash`).

To use real neural embeddings (`sentence-transformers/all-MiniLM-L6-v2`):

```powershell
pip install sentence-transformers
```

Set in `.env.local`:

```env
TOKENSHIELD_EMBEDDING_BACKEND=sentence-transformers
```

## Run

```powershell
python -m uvicorn app.main:app --reload
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Embedding smoke test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/embed -Method Post -ContentType "application/json" -Body '{"text":"What is semantic caching?"}'
```

Chat proxy test after adding `AI_GATEWAY_API_KEY`:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/chat/completions `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{"x-tokenshield-session"="demo"} `
  -Body '{"messages":[{"role":"user","content":"Invent a new holiday and describe its traditions."}]}'
```

Run tests:

```powershell
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp
```

