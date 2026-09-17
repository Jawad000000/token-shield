from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self.init_schema()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            create table if not exists cache_entries (
                id integer primary key autoincrement,
                question text not null,
                question_hash text,
                answer text not null,
                vector_json text not null,
                model text not null,
                provider text not null,
                hit_count integer not null default 0,
                created_at text not null default current_timestamp
            );

            create table if not exists request_logs (
                id integer primary key autoincrement,
                request_id text,
                session_id text not null,
                provider text not null,
                model text not null,
                cache_hit integer not null,
                raw_input_tokens integer not null,
                optimized_input_tokens integer not null default 0,
                upstream_input_tokens integer not null,
                output_tokens integer not null,
                saved_tokens integer not null,
                strategies_json text not null default '[]',
                failover_used integer not null default 0,
                secrets_redacted integer not null default 0,
                pii_redacted integer not null default 0,
                guard_mode text not null default 'enabled',
                budget_mode text not null default 'saving',
                notes_deduplicated integer not null default 0,
                turns_shrunk integer not null default 0,
                cache text not null default 'MISS',
                provider_attempts_json text not null default '[]',
                code_pruned integer not null default 0,
                logs_folded integer not null default 0,
                json_compressed integer not null default 0,
                created_at text not null default current_timestamp
            );

            create table if not exists study_events (
                id integer primary key autoincrement,
                session_id text not null,
                request_id text not null,
                topic text not null,
                question text not null,
                answer text not null,
                cache_hit integer not null default 0,
                cache_type text not null default 'MISS',
                created_at text not null default current_timestamp
            );

            create index if not exists idx_study_events_session on study_events(session_id);
            create index if not exists idx_study_events_topic on study_events(session_id, topic);

            create table if not exists code_snapshots (
                id integer primary key autoincrement,
                session_id text not null,
                file_key text not null,
                code text not null,
                created_at text not null default current_timestamp
            );

            create index if not exists idx_code_snapshots on code_snapshots(session_id, file_key);
            """
        )
        self._ensure_cache_entries_columns()
        self._ensure_request_log_columns()
        self._conn.commit()

    def _ensure_cache_entries_columns(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("pragma table_info(cache_entries)").fetchall()
        }
        if "question_hash" not in existing:
            self._conn.execute("alter table cache_entries add column question_hash text")
        self._conn.execute("create index if not exists idx_cache_question_hash on cache_entries(question_hash)")

    def _ensure_request_log_columns(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("pragma table_info(request_logs)").fetchall()
        }
        columns = {
            "request_id": "text",
            "optimized_input_tokens": "integer not null default 0",
            "strategies_json": "text not null default '[]'",
            "failover_used": "integer not null default 0",
            "secrets_redacted": "integer not null default 0",
            "pii_redacted": "integer not null default 0",
            "guard_mode": "text not null default 'enabled'",
            "budget_mode": "text not null default 'saving'",
            "notes_deduplicated": "integer not null default 0",
            "turns_shrunk": "integer not null default 0",
            "cache": "text not null default 'MISS'",
            "provider_attempts_json": "text not null default '[]'",
            "code_pruned": "integer not null default 0",
            "logs_folded": "integer not null default 0",
            "json_compressed": "integer not null default 0",
        }
        for name, definition in columns.items():
            if name not in existing:
                self._conn.execute(f"alter table request_logs add column {name} {definition}")

    def insert_cache_entry(
        self,
        *,
        question: str,
        answer: str,
        vector: list[float],
        model: str,
        provider: str,
        question_hash: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            insert into cache_entries(question, question_hash, answer, vector_json, model, provider)
            values (?, ?, ?, ?, ?, ?)
            """,
            (question, question_hash, answer, json.dumps(vector), model, provider),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def exact_lookup(self, question_hash: str) -> dict[str, Any] | None:
        if not question_hash:
            return None
        row = self._conn.execute(
            "select * from cache_entries where question_hash = ? order by id desc limit 1",
            (question_hash,),
        ).fetchone()
        return dict(row) if row else None

    def list_cache_entries(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("select * from cache_entries order by id asc").fetchall()
        return [dict(row) for row in rows]

    def mark_cache_hit(self, entry_id: int) -> None:
        self._conn.execute("update cache_entries set hit_count = hit_count + 1 where id = ?", (entry_id,))
        self._conn.commit()

    def save_code_snapshot(self, session_id: str, file_key: str, code: str) -> None:
        self._conn.execute(
            """
            insert into code_snapshots(session_id, file_key, code)
            values (?, ?, ?)
            """,
            (session_id, file_key, code),
        )
        self._conn.commit()

    def get_latest_code_snapshot(self, session_id: str, file_key: str) -> str | None:
        row = self._conn.execute(
            """
            select code from code_snapshots
            where session_id = ? and file_key = ?
            order by id desc limit 1
            """,
            (session_id, file_key),
        ).fetchone()
        return str(row["code"]) if row else None

    def log_request(
        self,
        *,
        request_id: str,
        session_id: str,
        provider: str,
        model: str,
        cache_hit: bool,
        raw_input_tokens: int,
        optimized_input_tokens: int,
        upstream_input_tokens: int,
        output_tokens: int,
        saved_tokens: int,
        strategies: list[str],
        failover_used: bool,
        secrets_redacted: int = 0,
        pii_redacted: int = 0,
        guard_mode: str = "enabled",
        budget_mode: str = "saving",
        notes_deduplicated: int = 0,
        turns_shrunk: int = 0,
        cache: str = "MISS",
        provider_attempts: list[dict[str, Any]] | None = None,
        code_pruned: int = 0,
        logs_folded: int = 0,
        json_compressed: int = 0,
    ) -> None:
        self._conn.execute(
            """
            insert into request_logs(
                request_id, session_id, provider, model, cache_hit, raw_input_tokens,
                optimized_input_tokens, upstream_input_tokens, output_tokens, saved_tokens,
                strategies_json, failover_used, secrets_redacted, pii_redacted, guard_mode,
                budget_mode, notes_deduplicated, turns_shrunk, cache, provider_attempts_json,
                code_pruned, logs_folded, json_compressed
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                session_id,
                provider,
                model,
                int(cache_hit),
                raw_input_tokens,
                optimized_input_tokens,
                upstream_input_tokens,
                output_tokens,
                saved_tokens,
                json.dumps(strategies),
                int(failover_used),
                secrets_redacted,
                pii_redacted,
                guard_mode,
                budget_mode,
                notes_deduplicated,
                turns_shrunk,
                cache,
                json.dumps(provider_attempts or []),
                code_pruned,
                logs_folded,
                json_compressed,
            ),
        )
        self._conn.commit()

    def get_receipt(self, request_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "select * from request_logs where request_id = ? order by id desc limit 1",
            (request_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["strategies"] = json.loads(data.get("strategies_json") or "[]")
        except Exception:
            data["strategies"] = []
        try:
            data["provider_attempts"] = json.loads(data.get("provider_attempts_json") or "[]")
        except Exception:
            data["provider_attempts"] = []
        data["cache_hit"] = bool(data["cache_hit"])
        data["failover_used"] = bool(data.get("failover_used", 0))
        data["secrets_redacted"] = int(data.get("secrets_redacted") or 0)
        data["pii_redacted"] = int(data.get("pii_redacted") or 0)
        data["guard_mode"] = str(data.get("guard_mode") or "enabled")
        data["budget_mode"] = str(data.get("budget_mode") or "saving")
        data["notes_deduplicated"] = int(data.get("notes_deduplicated") or 0)
        data["turns_shrunk"] = int(data.get("turns_shrunk") or 0)
        data["code_pruned"] = int(data.get("code_pruned") or 0)
        data["logs_folded"] = int(data.get("logs_folded") or 0)
        data["json_compressed"] = int(data.get("json_compressed") or 0)

        study_row = self._conn.execute(
            "select topic, cache_hit, cache_type from study_events where request_id = ? order by id desc limit 1",
            (request_id,),
        ).fetchone()
        if study_row:
            data["study"] = {"topic": study_row["topic"]}

        from app.budgeter import estimate_output_tokens_saved, get_budget_output_cap
        from app.recommendations import build_recommendations

        mode = data["budget_mode"]
        data["max_output_tokens"] = get_budget_output_cap(mode)
        data["estimated_output_tokens_saved"] = estimate_output_tokens_saved(mode, int(data.get("output_tokens") or 0))
        data["recommendations"] = build_recommendations(data)
        return data

    def metrics(self) -> dict[str, Any]:
        row = self._conn.execute(
            """
            select
                count(*) as requests,
                coalesce(sum(cache_hit), 0) as cache_hits,
                coalesce(sum(raw_input_tokens), 0) as raw_input_tokens,
                coalesce(sum(optimized_input_tokens), 0) as optimized_input_tokens,
                coalesce(sum(upstream_input_tokens), 0) as upstream_input_tokens,
                coalesce(sum(output_tokens), 0) as output_tokens,
                coalesce(sum(saved_tokens), 0) as saved_tokens,
                coalesce(sum(failover_used), 0) as failovers,
                coalesce(sum(secrets_redacted), 0) as secrets_redacted,
                coalesce(sum(pii_redacted), 0) as pii_redacted,
                coalesce(sum(notes_deduplicated), 0) as notes_deduplicated,
                coalesce(sum(turns_shrunk), 0) as turns_shrunk,
                coalesce(sum(code_pruned), 0) as code_pruned,
                coalesce(sum(logs_folded), 0) as logs_folded,
                coalesce(sum(json_compressed), 0) as json_compressed
            from request_logs
            """
        ).fetchone()
        data = dict(row)
        requests = data["requests"] or 0
        data["cache_hit_rate"] = (data["cache_hits"] / requests) if requests else 0.0
        data["total_redactions"] = data["secrets_redacted"] + data["pii_redacted"]

        # 1. Breakdown by budget_mode
        budget_rows = self._conn.execute(
            "select budget_mode, count(*) as cnt from request_logs group by budget_mode"
        ).fetchall()
        data["budget_modes"] = {r["budget_mode"]: r["cnt"] for r in budget_rows}

        # 2. Ranking of top strategies
        strat_counter: Counter[str] = Counter()
        strat_rows = self._conn.execute("select strategies_json from request_logs").fetchall()
        for s_row in strat_rows:
            try:
                for strat in json.loads(s_row["strategies_json"]):
                    strat_counter[strat] += 1
            except Exception:
                pass
        data["top_strategies"] = dict(strat_counter.most_common())

        # 3. Student Cost Forecast & Quota Runway
        daily_quota = 50000
        used_tokens = int(data.get("upstream_input_tokens") or 0) + int(data.get("output_tokens") or 0)
        remaining_quota = max(0, daily_quota - used_tokens)
        avg_tokens_per_request = (used_tokens / requests) if requests > 0 else 350.0
        estimated_questions_left = int(remaining_quota / avg_tokens_per_request) if avg_tokens_per_request > 0 else 100

        budget_recommendation = "critical" if (used_tokens > daily_quota * 0.60 or estimated_questions_left < 20) else "saving"
        burn_rate_per_hour = max(100, int(avg_tokens_per_request * 10))
        runway_hours = round(remaining_quota / burn_rate_per_hour, 1)
        runway_critical_hours = round((remaining_quota / (burn_rate_per_hour * 0.45)), 1)
        runway_message = (
            f"At current pace, free quota lasts ~{runway_hours} hours. "
            f"Switch to Critical Mode to extend to ~{runway_critical_hours} hours."
        )

        data["forecast"] = {
            "daily_token_quota": daily_quota,
            "used_tokens": used_tokens,
            "remaining_quota": remaining_quota,
            "estimated_questions_left": estimated_questions_left,
            "projected_daily_tokens": int(used_tokens * 1.4) if requests > 0 else 0,
            "budget_mode_recommendation": budget_recommendation,
            "runway_hours": runway_hours,
            "runway_message": runway_message,
        }
        return data

    def record_study_event(
        self,
        *,
        session_id: str,
        request_id: str,
        topic: str,
        question: str,
        answer: str,
        cache_hit: bool,
        cache_type: str = "MISS",
    ) -> int:
        cursor = self._conn.execute(
            """
            insert into study_events(session_id, request_id, topic, question, answer, cache_hit, cache_type)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, request_id, topic, question, answer, int(cache_hit), cache_type),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_session_study_events(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "select * from study_events where session_id = ? order by id asc",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_session_topics(self, session_id: str) -> list[str]:
        rows = self._conn.execute(
            "select distinct topic from study_events where session_id = ? order by id asc",
            (session_id,),
        ).fetchall()
        return [row["topic"] for row in rows]

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            select
                count(*) as requests,
                coalesce(sum(cache_hit), 0) as cache_hits,
                coalesce(sum(raw_input_tokens), 0) as raw_input_tokens,
                coalesce(sum(optimized_input_tokens), 0) as optimized_input_tokens,
                coalesce(sum(upstream_input_tokens), 0) as upstream_input_tokens,
                coalesce(sum(output_tokens), 0) as output_tokens,
                coalesce(sum(saved_tokens), 0) as saved_tokens,
                coalesce(sum(failover_used), 0) as failovers,
                coalesce(sum(secrets_redacted), 0) as secrets_redacted,
                coalesce(sum(pii_redacted), 0) as pii_redacted
            from request_logs
            where session_id = ?
            """,
            (session_id,),
        ).fetchone()
        data = dict(row) if row else {}
        requests = data.get("requests", 0) or 0
        data["cache_hit_rate"] = (data["cache_hits"] / requests) if requests else 0.0
        data["total_redactions"] = (data.get("secrets_redacted", 0) or 0) + (data.get("pii_redacted", 0) or 0)
        return data

    def get_session_timeline(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "select * from request_logs where session_id = ? order by id asc",
            (session_id,),
        ).fetchall()
        events = []
        for r in rows:
            d = dict(r)
            try:
                strategies = json.loads(d.get("strategies_json") or "[]")
            except Exception:
                strategies = []

            try:
                provider_attempts = json.loads(d.get("provider_attempts_json") or "[]")
            except Exception:
                provider_attempts = []

            cache_val = d.get("cache")
            if not cache_val or cache_val == "MISS":
                if d.get("cache_hit"):
                    if "exact_cache" in strategies:
                        cache_val = "EXACT_HIT"
                    elif "semantic_cache_soft" in strategies:
                        cache_val = "SOFT_HIT"
                    else:
                        cache_val = "HIT"
                else:
                    cache_val = "MISS"

            events.append({
                "request_id": d.get("request_id"),
                "cache": cache_val,
                "provider": d.get("provider"),
                "model": d.get("model"),
                "raw_input_tokens": d.get("raw_input_tokens", 0),
                "optimized_input_tokens": d.get("optimized_input_tokens", 0),
                "saved_input_tokens": d.get("saved_tokens", 0),
                "strategies": strategies,
                "secrets_redacted": d.get("secrets_redacted", 0),
                "pii_redacted": d.get("pii_redacted", 0),
                "guard_mode": d.get("guard_mode", "enabled"),
                "budget_mode": d.get("budget_mode", "saving"),
                "provider_attempts": provider_attempts,
                "code_pruned": int(d.get("code_pruned") or 0),
                "created_at": d.get("created_at"),
            })
        return events
