# Phase 4: Exact + Semantic Cache Optimization

## 1. Executive Summary

In Phases 1–3, TokenShield introduced:
1. **Phase 1**: Proxy core, OpenAI compatibility, provider waterfall, and transparent receipt accounting.
2. **Phase 2**: Guard Mode (automatic redaction of API keys, JWTs, emails, phone numbers, SSNs, credit cards).
3. **Phase 3**: Unique query token reduction pipeline (session note deduplication, conversation history compression, and answer budget control).

**Phase 4 upgrades the caching engine into a multi-tiered architecture:**
- **Exact Cache (`EXACT_HIT`)**: Instant $O(1)$ lookup via normalized SHA-256 query hashes. Bypasses vector embedding and similarity search entirely, responding with zero upstream tokens and zero vector computation overhead.
- **Multi-Tier Semantic Cache Confidence**:
  - `EXACT_HIT`: Identical sanitized query ($O(1)$ hash match).
  - `HIT` ($\ge 0.95$ cosine similarity): High-confidence semantic equivalence.
  - `SOFT_HIT` ($0.90 \le \text{similarity} < 0.95$): High-similarity rephrasing served with zero upstream token spend.
  - `MISS` ($< 0.90$ similarity): Forwards to Phase 3 token reduction and upstream provider waterfall.
- **Dual-Backend Embeddings**: Fast, zero-dependency deterministic hash embeddings (default) with toggleable support for neural `sentence-transformers/all-MiniLM-L6-v2`.

---

## 2. Multi-Tier Cache Pipeline

```mermaid
flowchart TD
    A[Incoming Chat Request] --> B[Phase 2: Guard Mode Redaction]
    B --> C[Extract Contextual Cache Query]
    C --> D[Normalize & Hash Query: SHA-256]
    D --> E{Exact Cache Lookup: O(1)}
    
    E -- Match Found --> F[Cache Tier: EXACT_HIT]
    F --> Z[Return Cached Response: 100% Upstream Tokens Saved]
    
    E -- Miss --> G[Generate 384-Dim Vector Embedding]
    G --> H{Semantic Similarity Search}
    
    H -- Similarity >= 0.95 --> I[Cache Tier: HIT]
    I --> Z
    
    H -- 0.90 <= Similarity < 0.95 --> J[Cache Tier: SOFT_HIT]
    J --> Z
    
    H -- Similarity < 0.90 --> K[Cache Tier: MISS]
    K --> L[Phase 3: Deduplication + Shrinker + Budgeter]
    L --> M[Upstream Provider Waterfall]
    M --> N[Store in Cache: Question, Hash, Vector, Answer]
    N --> O[Return Upstream Response & Issue Receipt]
```

---

## 3. Core Capabilities

### 3.1 Normalization and O(1) Exact Cache
Exact cache matches identical user requests even across minor whitespace or formatting discrepancies:
- Strips leading and trailing whitespace.
- Collapses consecutive whitespace characters into a single space.
- Converts to lowercase.
- Computes SHA-256 hex digest of the canonical key.

Lookups query the indexed `question_hash` column on SQLite:
```sql
SELECT * FROM cache_entries WHERE question_hash = ? ORDER BY id DESC LIMIT 1;
```

### 3.2 Confidence Tiers & Decision Rules

| Tier | Condition | Upstream Tokens | Response Header `x-tokenshield-cache` | Strategy Recorded |
|---|---|---|---|---|
| **`EXACT_HIT`** | Hash matches normalized query | `0` | `EXACT_HIT` | `exact_cache` |
| **`HIT`** | Cosine similarity $\ge 0.95$ | `0` | `HIT` | `semantic_cache` |
| **`SOFT_HIT`** | $0.90 \le \text{similarity} < 0.95$ | `0` | `SOFT_HIT` | `semantic_cache_soft` |
| **`MISS`** | Similarity $< 0.90$ | Active | `MISS` | `provider_proxy` |

Configurable via environment variables:
```env
TOKENSHIELD_CACHE_HARD_THRESHOLD=0.95
TOKENSHIELD_CACHE_SOFT_THRESHOLD=0.90
```

### 3.3 Database Migration
The database automatically checks and migrates existing SQLite tables on startup:
```python
def _ensure_cache_entries_columns(self) -> None:
    existing = {
        row["name"]
        for row in self._conn.execute("pragma table_info(cache_entries)").fetchall()
    }
    if "question_hash" not in existing:
        self._conn.execute("alter table cache_entries add column question_hash text")
    self._conn.execute("create index if not exists idx_cache_question_hash on cache_entries(question_hash)")
```

### 3.4 Embedding Backends

1. **Hash Embedding (`hash`) [Default]**:
   - Deterministic 384-dimensional sparse hashed vector.
   - Zero external model downloads or PyTorch/C++ dependencies.
   - Extremely fast for local development and demos.

2. **Sentence Transformers (`sentence-transformers`) [Optional]**:
   - Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim normalized dense vector).
   - Activated via:
     ```env
     TOKENSHIELD_EMBEDDING_BACKEND=sentence-transformers
     ```

---

## 4. Verification Evidence

All 26 automated unit and integration tests pass cleanly:
- `tests/test_cache.py`:
  - `test_hash_embedding_dimension_and_similarity`
  - `test_cache_key_normalization_and_hashing`
  - `test_exact_lookup_and_hit_count`
  - `test_dual_threshold_confidence_tiers`
- `tests/test_chat_cache.py`:
  - `test_chat_endpoint_can_return_cache_hit` (`EXACT_HIT`)
  - `test_chat_endpoint_miss_then_hit_skips_second_upstream_call`
  - `test_chat_endpoint_semantic_soft_hit_and_hit` (`HIT` & `SOFT_HIT`)
- Full proxy, guard mode, receipts, and shrinker regression tests.
