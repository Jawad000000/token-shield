from __future__ import annotations

from typing import Any


def build_recommendations(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Analyzes a request receipt and generates actionable, student-focused
    recommendations on how to save more tokens and study more efficiently.
    """
    recommendations: list[dict[str, Any]] = []

    cache_status = str(receipt.get("cache") or "MISS").upper()
    output_tokens = int(receipt.get("output_tokens") or 0)
    budget_mode = str(receipt.get("budget_mode") or "saving").lower()
    raw_in = int(receipt.get("raw_input_tokens") or 0)
    saved_in = int(receipt.get("saved_input_tokens") or 0)
    notes_count = int(receipt.get("notes_deduplicated") or 0)
    code_count = int(receipt.get("code_pruned") or 0)
    failover = bool(receipt.get("failover", False))
    study = receipt.get("study") if isinstance(receipt.get("study"), dict) else {}

    # 1. Zero-Cost Cache Hit Celebration
    if cache_status in {"HIT", "EXACT_HIT", "SOFT_HIT"}:
        label = "exact cache" if cache_status == "EXACT_HIT" else "semantic cache"
        recommendations.append({
            "type": "cache",
            "title": "Zero Upstream Token Cost",
            "message": f"This response was fulfilled instantly from {label} with 0 upstream API tokens billed.",
            "action": "Explore Similar Questions",
        })

    # 2. Output Budget / Hint Mode Tip
    saved_out = int(receipt.get("estimated_output_tokens_saved") or 0)
    if output_tokens > 250 or budget_mode == "normal":
        recommendations.append({
            "type": "output_budget",
            "title": "Use Hint / Critical Mode",
            "message": f"This answer used {output_tokens} output tokens. Critical/Hint Mode caps output to 120 tokens (~60% savings).",
            "action": "Switch to Critical Mode",
        })
    elif budget_mode == "critical":
        recommendations.append({
            "type": "output_budget",
            "title": "Critical Hint Mode Active",
            "message": f"Critical mode capped this output to {output_tokens} tokens (saved ~{saved_out} tokens vs normal baseline).",
            "action": "Maintain Critical Budget",
        })

    # 3. Flashcards / Weak Topic Consolidated Study
    if study.get("struggling") or int(study.get("repeat_count") or 0) >= 2:
        topic = str(study.get("topic") or "this topic")
        count = int(study.get("repeat_count") or 2)
        recommendations.append({
            "type": "study",
            "title": "Flashcards Ready",
            "message": f"You've asked about '{topic}' {count} times. Generate a 5-minute revision package and quiz.",
            "action": "Finish Session",
        })

    # 4. Note Deduplication Feedback
    if notes_count > 0:
        recommendations.append({
            "type": "notes",
            "title": "Repeated Notes Compressed",
            "message": f"{notes_count} repetitive note blocks in your session were replaced with compact reference tags.",
            "action": "Reuse Note Tags",
        })

    # 5. Code Pruning / Diff Feedback
    if code_count > 0:
        recommendations.append({
            "type": "code",
            "title": "Code Diff Pruning Active",
            "message": "Your updated code was sent upstream as a compact AST diff against your previous turn instead of resending the full file.",
            "action": "Continue Iterating",
        })

    # 6. Provider Failover Shield
    if failover:
        provider = str(receipt.get("provider") or "backup provider")
        recommendations.append({
            "type": "failover",
            "title": "Provider Shield Active",
            "message": f"Primary provider hit rate limits or downtime; TokenShield seamlessly routed your query to {provider}.",
            "action": "Check Provider Status",
        })

    logs_folded = int(receipt.get("logs_folded") or 0)
    json_compressed = int(receipt.get("json_compressed") or 0)

    # 7. Terminal / Log Folding Feedback
    if logs_folded > 0:
        recommendations.append({
            "type": "logs",
            "title": "Terminal Noise Folded",
            "message": f"{logs_folded} repetitive log lines were folded, keeping error traces 100% intact.",
            "action": "Keep Pasting Logs",
        })

    # 8. JSON Lossless SmartCrusher Feedback
    if json_compressed > 0:
        recommendations.append({
            "type": "json",
            "title": "JSON Losslessly Compacted",
            "message": f"{json_compressed} JSON blocks were stripped of indentation waste with zero data loss.",
            "action": "Send Raw JSON",
        })

    # 9. Prompt Shortening Advice
    if raw_in > 800 and saved_in < (raw_in * 0.20) and cache_status == "MISS":
        recommendations.append({
            "type": "prompt",
            "title": "Shorter Prompt Tip",
            "message": "Large prompt with low compression. Try asking: 'Explain in 5 bullets with 1 example' or uploading reference notes once.",
            "action": "Apply Prompt Tip",
        })

    return recommendations
