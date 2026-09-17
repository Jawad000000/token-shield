import math
from app.cache import (
    SemanticCache,
    cosine_similarity,
    hash_cache_key,
    normalize_cache_key,
)
from app.db import Database
from app.embeddings import HashEmbeddingService


def test_hash_embedding_dimension_and_similarity() -> None:
    embedder = HashEmbeddingService()
    first = embedder.embed_text("What is semantic caching?")
    repeat = embedder.embed_text("What is semantic caching?")

    assert len(first) == 384
    assert cosine_similarity(first, repeat) == 1.0


def test_cache_key_normalization_and_hashing() -> None:
    raw1 = "  What is   TokenShield? \n"
    raw2 = "what is tokenshield?"
    raw3 = "what is tokenshield? "

    norm1 = normalize_cache_key(raw1)
    norm2 = normalize_cache_key(raw2)
    norm3 = normalize_cache_key(raw3)

    assert norm1 == norm2 == norm3 == "what is tokenshield?"
    assert hash_cache_key(raw1) == hash_cache_key(raw2) == hash_cache_key(raw3)


def test_exact_lookup_and_hit_count(tmp_path) -> None:
    db = Database(str(tmp_path / "exact_test.sqlite3"))
    cache = SemanticCache(db, hard_threshold=0.95, soft_threshold=0.90)

    dim = 384
    vec = [0.0] * dim
    vec[0] = 1.0

    entry_id = cache.store(
        question="Explain TCP handshake",
        answer="SYN -> SYN-ACK -> ACK",
        vector=vec,
        provider="test-p",
        model="test-m",
    )

    # Exact lookup with exact phrase
    hit = cache.exact_lookup("Explain TCP handshake")
    assert hit is not None
    assert hit.hit_type == "EXACT_HIT"
    assert hit.similarity == 1.0
    assert hit.answer == "SYN -> SYN-ACK -> ACK"
    assert hit.entry_id == entry_id

    # Exact lookup with case/whitespace variations
    hit2 = cache.exact_lookup("  explain   tcp handshake  ")
    assert hit2 is not None
    assert hit2.hit_type == "EXACT_HIT"

    # Exact lookup miss
    miss = cache.exact_lookup("Explain UDP handshake")
    assert miss is None

    # Check hit_count incremented in DB
    entries = db.list_cache_entries()
    assert entries[0]["hit_count"] == 2


def test_dual_threshold_confidence_tiers(tmp_path) -> None:
    db = Database(str(tmp_path / "tiers_test.sqlite3"))
    cache = SemanticCache(db, hard_threshold=0.95, soft_threshold=0.90)

    dim = 384
    base_vec = [0.0] * dim
    base_vec[0] = 1.0

    cache.store(
        question="Original question",
        answer="Original answer",
        vector=base_vec,
        provider="test-p",
        model="test-m",
    )

    # 1. Similarity >= 0.95 -> HIT
    vec_96 = [0.0] * dim
    vec_96[0] = 0.96
    vec_96[1] = math.sqrt(1.0 - 0.96**2)
    hit_hard = cache.lookup(vec_96)
    assert hit_hard is not None
    assert hit_hard.hit_type == "HIT"
    assert round(hit_hard.similarity, 2) == 0.96

    # 2. 0.90 <= Similarity < 0.95 -> SOFT_HIT
    vec_92 = [0.0] * dim
    vec_92[0] = 0.92
    vec_92[1] = math.sqrt(1.0 - 0.92**2)
    hit_soft = cache.lookup(vec_92)
    assert hit_soft is not None
    assert hit_soft.hit_type == "SOFT_HIT"
    assert round(hit_soft.similarity, 2) == 0.92

    # 3. Similarity < 0.90 -> MISS (None)
    vec_85 = [0.0] * dim
    vec_85[0] = 0.85
    vec_85[1] = math.sqrt(1.0 - 0.85**2)
    hit_miss = cache.lookup(vec_85)
    assert hit_miss is None
