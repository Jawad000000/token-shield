# TokenShield

**The Auditable LLM Token Optimization Proxy.**
Get a transparent, per-request **Token Receipt** attributing exact savings across multi-tier semantic caching, lossless log folding, AST code pruning, Guard Mode credential redaction, and intelligent provider routing—without destroying response quality.

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

### 4. Run Test Suite (174 Tests Passing)
```bash
python -m pytest -p no:cacheprovider --basetemp=.tokenshield/pytest_temp -q
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

## Receipt Integrity

The receipt is the product, so its numbers are held to a few rules:

- **Savings are computed inside one tokenizer.** `saved_input_tokens` is always
  `raw_input_tokens - optimized_input_tokens`, both measured with TokenShield's own
  encoder. The provider's billed prompt count is reported separately as
  `upstream_input_tokens`, tagged with `upstream_token_source` (`provider`, `estimated`,
  or `cache`). The two are never subtracted from each other, because providers use
  different tokenizers and the difference would be noise, not savings.
- **The receipt and `/metrics/live` always agree.** Both read the same figure.
- **Output savings say what they are based on.** `output_savings_basis` is
  `measured_avg` once this deployment has enough of its own unconstrained (`normal`
  mode) responses to average, and `default_baseline` before that. The comparison
  baseline is exposed as `output_baseline_tokens`.
- **Truncated answers are not savings.** If an answer stops because it hit the cap
  (`finish_reason == "length"`), the receipt sets `truncated: true`, adds the
  `output_truncated` strategy, and reports zero output savings. A cut-off answer costs
  full price and is unusable.
- **Caps are only reported when applied.** `max_output_tokens_applied` shows whether a
  cap was actually sent upstream. Outside `critical` mode, TokenShield shapes answer
  length through the budget directive rather than a hard cap, because prompt-level
  instructions compress and hard caps truncate.

## Verified Soft Hits

A `SOFT_HIT` (0.90–0.95 cosine) is a *close vector match*, which is not the same thing
as a correct answer. Before serving one, TokenShield spends a handful of tokens asking
the cheapest configured provider a single yes/no question: does this cached answer
actually answer the new question?

- Accepted → served from cache, zero generation tokens, badge shows `SOFT_HIT ✓ VERIFIED`.
- Rejected → falls through to a real upstream call, `soft_hit_rejected` appears in the
  strategy list, and the receipt records the verdict.
- Verifier unavailable or unparseable → fails open and serves the hit, so a broken
  checker never blocks a working cache.

Toggle with `TOKENSHIELD_VERIFY_SOFT_HITS`.

## Conversation Shrinking

Older turns are summarized; the most recent turns are kept **byte-for-byte**
(`TOKENSHIELD_VERBATIM_TURNS`, default 2). Truncating recent history to a one-line
summary is where answer quality goes to die, and input tokens are the cheaper half of
the bill — so the shrinker trades a little compression for fidelity where it counts.

The rebuilt system block is ordered **stable content first**: system instructions, then
the budget directive, then the append-only summary. That keeps a constant prefix across
turns so provider prompt-prefix caching can match it.

## Caching & Optimization

TokenShield employs a multi-tier cache to maximize token savings:

1. **Exact Cache (`EXACT_HIT`)**: Normalized SHA-256 hash lookup (`O(1)`). Identical queries hit instantly without embedding or vector math.
2. **Semantic Cache (`HIT`)**: Cosine similarity $\ge$ `0.95` (configurable via `TOKENSHIELD_CACHE_HARD_THRESHOLD`). Rephrased queries return cached response with zero upstream tokens.
3. **Soft Hit (`SOFT_HIT`)**: Cosine similarity between `0.90` and `0.95` (configurable via `TOKENSHIELD_CACHE_SOFT_THRESHOLD`). High confidence semantic match.
4. **Cache Miss (`MISS`)**: Executes unique query token reduction pipeline (Guard Mode redaction, session note deduplication, and conversation shrinker/budgeter) before calling upstream provider.

### Embedding Backend

By default, TokenShield uses a fast, deterministic, zero-dependency 384-dimensional hash embedding backend (`hash`).

> **Use `sentence-transformers` for any real demo.** The `hash` backend is a signed
> bag-of-words projection: it has no notion of word order or negation, so "how do I sort
> this list" and "how do I *not* sort this list" land in nearly the same place. It exists
> so the project runs with zero extra dependencies, not because it is accurate.

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

