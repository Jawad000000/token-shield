from __future__ import annotations

import uuid
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict

from app.budgeter import (
    estimate_output_tokens_saved,
    get_budget_directive,
    get_budget_output_cap,
    resolve_budget_mode,
)
from app.cache import SemanticCache, build_cache_query, hash_cache_key
from app.code_pruning import prune_code_snippets
from app.binary_detector import detect_binary_in_messages
from app.comment_stripper import strip_comments_in_messages
from app.config import get_settings
from app.db import Database
from app.embeddings import build_embedding_service
from app.guard import redact_messages
from app.json_compressor import compress_json_in_messages
from app.log_folding import fold_logs_in_messages
from app.memory import deduplicate_session_notes
from app.normalizer import normalize_messages
from app.phrase_compactor import compact_phrases_in_messages
from app.providers import ProviderError, ProviderRouter
from app.recommendations import build_recommendations
from app.shrinker import shrink_conversation
from app.study import assess_struggle, extract_topic, generate_study_package
from app.tokens import estimate_message_tokens, estimate_text_tokens
from app.verifier import SoftHitVerifier, VerificationResult


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    stream: bool = False

    model_config = ConfigDict(extra="allow")


class EmbedRequest(BaseModel):
    text: str


settings = get_settings()
db = Database(settings.db_path)
embeddings = build_embedding_service(settings.embedding_backend)
semantic_cache = SemanticCache(
    db,
    hard_threshold=settings.cache_hard_threshold,
    soft_threshold=settings.cache_soft_threshold,
)
providers = ProviderRouter(settings.providers)
soft_hit_verifier = SoftHitVerifier(
    settings.providers,
    enabled=settings.verify_soft_hits,
)
app = FastAPI(title="TokenShield")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def cached_chat_response(request: ChatCompletionRequest, answer: str, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"tokenshield-cache-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": 0,
        "model": request.model or "tokenshield-cache",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "tokenshield": receipt,
    }


def assistant_text(payload: dict[str, Any]) -> str:
    try:
        return payload["choices"][0]["message"]["content"] or ""
    except Exception:
        return ""


def set_tokenshield_headers(response: Response, receipt: dict[str, Any]) -> None:
    response.headers["x-tokenshield-request-id"] = str(receipt["request_id"])
    response.headers["x-tokenshield-cache"] = str(receipt["cache"])
    response.headers["x-tokenshield-provider"] = str(receipt["provider"])
    response.headers["x-tokenshield-failover"] = str(receipt["failover"]).lower()
    response.headers["x-tokenshield-raw-input-tokens"] = str(receipt["raw_input_tokens"])
    response.headers["x-tokenshield-optimized-input-tokens"] = str(receipt["optimized_input_tokens"])
    response.headers["x-tokenshield-upstream-input-tokens"] = str(receipt["upstream_input_tokens"])
    response.headers["x-tokenshield-saved-input-tokens"] = str(receipt["saved_input_tokens"])
    response.headers["x-tokenshield-strategies"] = ",".join(receipt["strategies"])
    response.headers["x-tokenshield-guard-mode"] = str(receipt.get("guard_mode", "enabled"))
    response.headers["x-tokenshield-secrets-redacted"] = str(receipt.get("secrets_redacted", 0))
    response.headers["x-tokenshield-pii-redacted"] = str(receipt.get("pii_redacted", 0))
    response.headers["x-tokenshield-budget-mode"] = str(receipt.get("budget_mode", "saving"))
    response.headers["x-tokenshield-notes-deduplicated"] = str(receipt.get("notes_deduplicated", 0))
    response.headers["x-tokenshield-turns-shrunk"] = str(receipt.get("turns_shrunk", 0))
    response.headers["x-tokenshield-code-pruned"] = str(receipt.get("code_pruned", 0))
    response.headers["x-tokenshield-logs-folded"] = str(receipt.get("logs_folded", 0))
    response.headers["x-tokenshield-json-compressed"] = str(receipt.get("json_compressed", 0))
    response.headers["x-tokenshield-max-output-tokens"] = str(receipt.get("max_output_tokens", 700))
    response.headers["x-tokenshield-saved-output-tokens"] = str(receipt.get("estimated_output_tokens_saved", 0))
    response.headers["x-tokenshield-recommendations-count"] = str(len(receipt.get("recommendations", [])))
    response.headers["x-tokenshield-upstream-token-source"] = str(receipt.get("upstream_token_source", "estimated"))
    response.headers["x-tokenshield-output-savings-basis"] = str(receipt.get("output_savings_basis", "default_baseline"))
    response.headers["x-tokenshield-truncated"] = str(receipt.get("truncated", False)).lower()
    verification = receipt.get("soft_hit_verification")
    if isinstance(verification, dict) and verification.get("verdict"):
        response.headers["x-tokenshield-soft-hit-verdict"] = str(verification["verdict"])
    if "study" in receipt and isinstance(receipt["study"], dict):
        study_info = receipt["study"]
        if study_info.get("topic"):
            response.headers["x-tokenshield-topic"] = str(study_info["topic"])
        if study_info.get("struggling"):
            response.headers["x-tokenshield-struggling-topic"] = str(study_info["topic"])


UI_FILE_PATH = Path(__file__).resolve().parent.parent / "ui.html"


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def serve_ui() -> Response:
    if UI_FILE_PATH.is_file():
        return FileResponse(str(UI_FILE_PATH), media_type="text/html")
    return HTMLResponse("<h1>TokenShield UI not found</h1>", status_code=404)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "embedding_backend": settings.embedding_backend,
        "embedding_dimension": getattr(embeddings, "dimension", None),
        "providers": [
            {"name": provider.name, "configured": provider.configured, "model": provider.model}
            for provider in settings.providers
        ],
    }


@app.get("/providers/status")
def providers_status() -> list[dict[str, Any]]:
    return [
        {"name": provider.name, "configured": provider.configured, "model": provider.model}
        for provider in settings.providers
    ]


@app.post("/embed")
def embed(payload: EmbedRequest) -> dict[str, Any]:
    vector = embeddings.embed_text(payload.text)
    return {"dimension": len(vector), "vector_preview": vector[:8]}


@app.get("/metrics/live")
def live_metrics() -> dict[str, Any]:
    return db.metrics()


@app.get("/receipt/{request_id}")
def get_receipt(request_id: str) -> dict[str, Any]:
    receipt = db.get_receipt(request_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Receipt '{request_id}' not found.")
    return receipt


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    response: Response,
    x_tokenshield_session: str | None = Header(default=None),
    x_tokenshield_budget_mode: str | None = Header(default=None),
) -> dict[str, Any]:
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not implemented in this TokenShield slice yet.")

    MAX_MESSAGES = 50
    if len(request.messages) > MAX_MESSAGES:
        raise HTTPException(status_code=400, detail=f"Max {MAX_MESSAGES} messages per request.")

    session_id = x_tokenshield_session or "default"
    request_id = uuid.uuid4().hex

    # 1. Raw tokens from original client messages
    raw_input_tokens = estimate_message_tokens(request.messages)

    # 2. Guard Mode: redact secrets and PII (never mutates request object)
    redacted_messages, guard_result = redact_messages(request.messages)

    # 3. Check exact cache first (O(1)), then semantic cache
    cache_query = build_cache_query(redacted_messages)
    question_hash = hash_cache_key(cache_query) if cache_query else ""

    # Phase 5: Student Study Topic & Struggle Tracking
    session_events = db.get_session_study_events(session_id)
    existing_topics = [e["topic"] for e in session_events]
    study_topic = extract_topic(cache_query, existing_topics=existing_topics)
    is_struggling, repeat_count = assess_struggle(session_events, study_topic)
    study_receipt = {
        "topic": study_topic,
        "struggling": is_struggling,
        "repeat_count": repeat_count,
    }

    cache_hit = semantic_cache.exact_lookup(question_hash=question_hash) if question_hash else None
    vector: list[float] | None = None
    if not cache_hit and cache_query:
        vector = embeddings.embed_text(cache_query)
        cache_hit = semantic_cache.lookup(vector)

    budget_mode = resolve_budget_mode(x_tokenshield_budget_mode, raw_input_tokens)

    base_strategies = ["guard_mode"]
    if guard_result.secrets_redacted > 0:
        base_strategies.append("secret_redaction")
    if guard_result.pii_redacted > 0:
        base_strategies.append("pii_redaction")

    # Verify borderline semantic matches before serving them as answers. A SOFT_HIT is
    # a "close enough" vector match, which is not the same as a correct answer -- so we
    # spend a few tokens on the cheapest provider to confirm before trusting it.
    soft_verification: VerificationResult | None = None
    if cache_hit and cache_hit.hit_type == "SOFT_HIT" and soft_hit_verifier.available:
        soft_verification = await soft_hit_verifier.verify(cache_query, cache_hit.answer)
        if soft_verification.rejected:
            cache_hit = None
            base_strategies.append("soft_hit_rejected")

    output_baseline = db.output_baseline()

    if cache_hit:
        answer_tokens = estimate_text_tokens(cache_hit.answer)
        output_cap = get_budget_output_cap(budget_mode)
        saved_output_tokens = estimate_output_tokens_saved(
            budget_mode, answer_tokens, baseline=output_baseline["baseline"]
        )
        if cache_hit.hit_type == "EXACT_HIT":
            cache_label = "EXACT_HIT"
            cache_strategy = "exact_cache"
        elif cache_hit.hit_type == "SOFT_HIT":
            cache_label = "SOFT_HIT"
            cache_strategy = "semantic_cache_soft"
        else:
            cache_label = "HIT"
            cache_strategy = "semantic_cache"

        strategies = base_strategies + [cache_strategy]
        receipt = {
            "request_id": request_id,
            "cache": cache_label,
            "provider": "cache",
            "model": cache_hit.model,
            "failover": False,
            "raw_input_tokens": raw_input_tokens,
            "optimized_input_tokens": raw_input_tokens,
            "upstream_input_tokens": 0,
            "saved_input_tokens": raw_input_tokens,
            "output_tokens": answer_tokens,
            "max_output_tokens": output_cap,
            "estimated_output_tokens_saved": saved_output_tokens,
            "strategies": strategies,
            "secrets_redacted": guard_result.secrets_redacted,
            "pii_redacted": guard_result.pii_redacted,
            "guard_mode": guard_result.guard_mode,
            "budget_mode": budget_mode,
            "notes_deduplicated": 0,
            "turns_shrunk": 0,
            "provider_attempts": [],
            "code_pruned": 0,
            "logs_folded": 0,
            "json_compressed": 0,
            "study": study_receipt,
            "upstream_token_source": "cache",
            "output_savings_basis": output_baseline["basis"],
            "output_baseline_tokens": output_baseline["baseline"] or 700,
            "max_output_tokens_applied": False,
            "truncated": False,
            "soft_hit_verification": soft_verification.as_receipt() if soft_verification else None,
        }
        receipt["recommendations"] = build_recommendations(receipt)
        db.log_request(
            request_id=request_id,
            session_id=session_id,
            provider="cache",
            model=cache_hit.model,
            cache_hit=True,
            raw_input_tokens=raw_input_tokens,
            optimized_input_tokens=raw_input_tokens,
            upstream_input_tokens=0,
            output_tokens=answer_tokens,
            saved_tokens=raw_input_tokens,
            strategies=strategies,
            failover_used=False,
            secrets_redacted=guard_result.secrets_redacted,
            pii_redacted=guard_result.pii_redacted,
            guard_mode=guard_result.guard_mode,
            budget_mode=budget_mode,
            notes_deduplicated=0,
            turns_shrunk=0,
            cache=cache_label,
            provider_attempts=[],
            code_pruned=0,
            logs_folded=0,
            json_compressed=0,
        )
        db.record_study_event(
            session_id=session_id,
            request_id=request_id,
            topic=study_topic,
            question=cache_query,
            answer=cache_hit.answer,
            cache_hit=True,
            cache_type=cache_hit.hit_type,
        )
        response.headers["x-tokenshield-similarity"] = f"{cache_hit.similarity:.4f}"
        set_tokenshield_headers(response, receipt)
        return cached_chat_response(request, cache_hit.answer, receipt)

    # 4. On Cache MISS (Unique Query Token Reduction Pipeline)
    # Step A: Deduplicate repeated notes in the session
    deduped_messages, notes_deduped_count = deduplicate_session_notes(redacted_messages, session_id)
    if notes_deduped_count > 0:
        base_strategies.append("note_deduplication")

    # Step B: Prune repeated code snapshots against previous turns in the session
    code_pruned_messages, code_pruned_count = prune_code_snippets(deduped_messages, session_id, db)
    if code_pruned_count > 0:
        base_strategies.append("code_pruning")

    # Step C: Fold verbose terminal/compiler logs
    log_folded_messages, logs_folded_count = fold_logs_in_messages(code_pruned_messages)
    if logs_folded_count > 0:
        base_strategies.append("log_folding")

    # Step D: Losslessly minify and compress structured JSON payloads
    json_compressed_messages, json_compressed_count = compress_json_in_messages(log_folded_messages)
    if json_compressed_count > 0:
        base_strategies.append("json_compression")

    # Step D2: Strip comments from code blocks (models don't need human comments)
    comment_stripped_messages, comments_stripped_count = strip_comments_in_messages(json_compressed_messages)
    if comments_stripped_count > 0:
        base_strategies.append("comment_stripping")

    # Step D2.5: Detect and replace base64 data, hex dumps, and long hashes
    binary_cleaned_messages, binary_replaced_count = detect_binary_in_messages(comment_stripped_messages)
    if binary_replaced_count > 0:
        base_strategies.append("binary_data_detection")

    # Step D3: Compact verbose phrases ("in order to" → "to", etc.)
    phrase_compacted_messages, phrases_compacted_count = compact_phrases_in_messages(binary_cleaned_messages)
    if phrases_compacted_count > 0:
        base_strategies.append("phrase_compaction")

    # Step D4: Lossless structural normalization (Markdown tables, delimiter runs, tracking URLs, whitespace)
    normalized_messages, norm_mods_count = normalize_messages(phrase_compacted_messages)
    if norm_mods_count > 0:
        base_strategies.append("structural_normalization")

    # Step E: Shrink multi-turn conversation and inject answer budget directive
    optimized_messages, shrink_result = shrink_conversation(
        normalized_messages,
        requested_budget_mode=budget_mode,
        raw_tokens=raw_input_tokens,
    )
    if shrink_result.applied:
        base_strategies.append("conversation_shrinker")
    if shrink_result.budget_mode != "normal":
        base_strategies.append(f"budget_{shrink_result.budget_mode}")

    optimized_input_tokens = estimate_message_tokens(optimized_messages)
    if optimized_input_tokens > raw_input_tokens:
        # Guard: Never inflate input tokens if directive added more than shrinking saved
        optimized_messages = redacted_messages
        optimized_input_tokens = raw_input_tokens
        saved_input_tokens = 0
        notes_deduped_count = 0
        turns_shrunk_count = 0
        code_pruned_count = 0
        logs_folded_count = 0
        json_compressed_count = 0
        comments_stripped_count = 0
        phrases_compacted_count = 0
        # Revert misleading strategies
        base_strategies = [s for s in base_strategies if s in ("guard_mode", "secret_redaction", "pii_redaction")]
        base_strategies.append("optimization_reverted_no_savings")
    else:
        turns_shrunk_count = shrink_result.turns_shrunk
        saved_input_tokens = max(0, raw_input_tokens - optimized_input_tokens)

    output_cap = get_budget_output_cap(shrink_result.budget_mode)

    try:
        payload = request.model_dump(exclude_none=True)
        # CRITICAL: Always pass sanitized, optimized messages upstream
        payload["messages"] = optimized_messages
        if "max_tokens" in payload and payload["max_tokens"] is not None:
            payload["max_tokens"] = int(payload["max_tokens"])
        elif shrink_result.budget_mode == "critical":
            payload["max_tokens"] = output_cap
        applied_max_tokens = payload.get("max_tokens")
        upstream_result = await providers.chat_completion(payload)
        upstream_response, provider, used_failover = upstream_result[:3]
    except ProviderError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    if hasattr(upstream_result, "attempts") and upstream_result.attempts:
        provider_attempts = upstream_result.attempts
    elif len(upstream_result) >= 4:
        provider_attempts = upstream_result[3]
    else:
        provider_attempts = [{"provider": provider.name, "status": 200}]

    answer = assistant_text(upstream_response)
    usage_data = upstream_response.get("usage") if isinstance(upstream_response, dict) else None
    if usage_data and isinstance(usage_data, dict) and usage_data.get("completion_tokens"):
        output_tokens = int(usage_data["completion_tokens"])
    else:
        output_tokens = estimate_text_tokens(answer)

    if usage_data and isinstance(usage_data, dict) and usage_data.get("prompt_tokens"):
        actual_upstream_input = int(usage_data["prompt_tokens"])
        upstream_token_source = "provider"
    else:
        actual_upstream_input = optimized_input_tokens
        upstream_token_source = "estimated"

    saved_output_tokens = estimate_output_tokens_saved(
        shrink_result.budget_mode, output_tokens, baseline=output_baseline["baseline"]
    )

    # A capped answer that stops mid-sentence costs full price and is unusable.
    # Surface it instead of silently reporting it as a saving.
    finish_reason = ""
    try:
        finish_reason = str(upstream_response["choices"][0].get("finish_reason") or "")
    except Exception:
        finish_reason = ""
    truncated = finish_reason == "length"
    if truncated:
        saved_output_tokens = 0

    strategies = base_strategies + ["provider_proxy"]
    if used_failover:
        strategies.append("provider_waterfall")
    if truncated:
        strategies.append("output_truncated")

    receipt = {
        "request_id": request_id,
        "cache": "MISS",
        "provider": provider.name,
        "model": provider.model,
        "failover": used_failover,
        "raw_input_tokens": raw_input_tokens,
        "optimized_input_tokens": optimized_input_tokens,
        # saved_input_tokens compares raw vs optimized using OUR tokenizer on both sides.
        # upstream_input_tokens is the provider's own count and may use a different
        # tokenizer entirely, so the two are reported side by side, never subtracted.
        "upstream_input_tokens": actual_upstream_input,
        "upstream_token_source": upstream_token_source,
        "saved_input_tokens": saved_input_tokens,
        "output_tokens": output_tokens,
        "max_output_tokens": applied_max_tokens if applied_max_tokens else output_cap,
        "max_output_tokens_applied": applied_max_tokens is not None,
        "estimated_output_tokens_saved": saved_output_tokens,
        "output_savings_basis": output_baseline["basis"],
        "output_baseline_tokens": output_baseline["baseline"] or 700,
        "truncated": truncated,
        "finish_reason": finish_reason,
        "soft_hit_verification": soft_verification.as_receipt() if soft_verification else None,
        "strategies": strategies,
        "secrets_redacted": guard_result.secrets_redacted,
        "pii_redacted": guard_result.pii_redacted,
        "guard_mode": guard_result.guard_mode,
        "budget_mode": shrink_result.budget_mode,
        "notes_deduplicated": notes_deduped_count,
        "turns_shrunk": turns_shrunk_count,
        "provider_attempts": provider_attempts,
        "code_pruned": code_pruned_count,
        "logs_folded": logs_folded_count,
        "json_compressed": json_compressed_count,
        "comments_stripped": comments_stripped_count,
        "phrases_compacted": phrases_compacted_count,
        "study": study_receipt,
    }
    receipt["recommendations"] = build_recommendations(receipt)
    # Store sanitized text and question_hash in the cache
    if vector is None and cache_query:
        vector = embeddings.embed_text(cache_query)
    elif vector is None:
        dim = getattr(embeddings, "dimension", 384)
        vector = [0.0] * dim

    semantic_cache.store(
        question=cache_query,
        answer=answer,
        vector=vector,
        provider=provider.name,
        model=provider.model,
        question_hash=question_hash,
    )
    db.log_request(
        request_id=request_id,
        session_id=session_id,
        provider=provider.name,
        model=provider.model,
        cache_hit=False,
        raw_input_tokens=raw_input_tokens,
        optimized_input_tokens=optimized_input_tokens,
        upstream_input_tokens=actual_upstream_input,
        output_tokens=output_tokens,
        saved_tokens=saved_input_tokens,
        strategies=strategies,
        failover_used=used_failover,
        secrets_redacted=guard_result.secrets_redacted,
        pii_redacted=guard_result.pii_redacted,
        guard_mode=guard_result.guard_mode,
        budget_mode=shrink_result.budget_mode,
        notes_deduplicated=notes_deduped_count,
        turns_shrunk=turns_shrunk_count,
        cache="MISS",
        provider_attempts=provider_attempts,
        code_pruned=code_pruned_count,
        logs_folded=logs_folded_count,
        json_compressed=json_compressed_count,
        comments_stripped=comments_stripped_count,
        phrases_compacted=phrases_compacted_count,
    )
    db.record_study_event(
        session_id=session_id,
        request_id=request_id,
        topic=study_topic,
        question=cache_query,
        answer=answer,
        cache_hit=False,
        cache_type="MISS",
    )
    set_tokenshield_headers(response, receipt)
    upstream_response["tokenshield"] = receipt
    return upstream_response


@app.get("/session/{session_id}/timeline")
def session_timeline(session_id: str) -> list[dict[str, Any]]:
    return db.get_session_timeline(session_id)


@app.post("/session/{session_id}/finish")
def finish_session(session_id: str) -> dict[str, Any]:
    events = db.get_session_study_events(session_id)
    stats = db.get_session_stats(session_id)
    if not events and not stats.get("requests"):
        raise HTTPException(status_code=404, detail=f"No activity found for session '{session_id}'.")
    return generate_study_package(session_id, events, stats)
