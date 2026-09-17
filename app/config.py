from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv_local(path: str = ".env.local") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class Settings:
    cache_threshold: float
    cache_hard_threshold: float
    cache_soft_threshold: float
    db_path: str
    embedding_backend: str
    providers: tuple[ProviderConfig, ...]


def indexed_provider_configs(max_providers: int = 20) -> tuple[ProviderConfig, ...]:
    providers: list[ProviderConfig] = []
    for index in range(1, max_providers + 1):
        prefix = f"TOKENSHIELD_PROVIDER_{index}"
        name = os.getenv(f"{prefix}_NAME")
        base_url = os.getenv(f"{prefix}_BASE_URL")
        api_key_env = os.getenv(f"{prefix}_API_KEY_ENV")
        model = os.getenv(f"{prefix}_MODEL")
        if not any((name, base_url, api_key_env, model)):
            continue
        if not all((name, base_url, api_key_env, model)):
            missing = [
                key
                for key, value in {
                    "NAME": name,
                    "BASE_URL": base_url,
                    "API_KEY_ENV": api_key_env,
                    "MODEL": model,
                }.items()
                if not value
            ]
            raise ValueError(f"{prefix} is incomplete; missing {', '.join(missing)}")
        providers.append(
            ProviderConfig(
                name=name,
                base_url=base_url,
                api_key_env=api_key_env,
                model=model,
            )
        )
    return tuple(providers)


def default_provider_configs() -> tuple[ProviderConfig, ...]:
    providers: list[ProviderConfig] = [
        ProviderConfig(
            name="vercel",
            base_url=os.getenv("VERCEL_AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1"),
            api_key_env="AI_GATEWAY_API_KEY",
            model=os.getenv("TOKENSHIELD_PRIMARY_MODEL", "openai/gpt-5.5"),
        ),
        ProviderConfig(
            name="google",
            base_url=os.getenv("GOOGLE_OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
            api_key_env="GOOGLE_API_KEY",
            model=os.getenv("GOOGLE_MODEL", "gemini-3.6-flash"),
        ),
    ]
    if os.getenv("OLLAMA_API_KEY") or os.getenv("OLLAMA_BASE_URL"):
        providers.append(
            ProviderConfig(
                name="ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1"),
                api_key_env="OLLAMA_API_KEY",
                model=os.getenv("OLLAMA_MODEL", "gpt-oss:20b"),
            )
        )
    if os.getenv("KILO_API_KEY") or os.getenv("KILO_BASE_URL"):
        providers.append(
            ProviderConfig(
                name="kilo",
                base_url=os.getenv("KILO_BASE_URL", "https://api.kilo.ai/api/gateway"),
                api_key_env="KILO_API_KEY",
                model=os.getenv("KILO_MODEL", "openrouter/free"),
            )
        )
    providers.append(
        ProviderConfig(
            name="groq",
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key_env="GROQ_API_KEY",
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        )
    )
    return tuple(providers)


def get_settings() -> Settings:
    load_dotenv_local()
    providers = indexed_provider_configs() or default_provider_configs()
    hard_thresh_env = os.getenv("TOKENSHIELD_CACHE_HARD_THRESHOLD")
    soft_thresh_env = os.getenv("TOKENSHIELD_CACHE_SOFT_THRESHOLD")
    legacy_thresh_env = os.getenv("TOKENSHIELD_CACHE_THRESHOLD")

    hard_threshold = float(hard_thresh_env) if hard_thresh_env else (float(legacy_thresh_env) if legacy_thresh_env else 0.95)
    soft_threshold = float(soft_thresh_env) if soft_thresh_env else 0.90
    legacy_threshold = float(legacy_thresh_env) if legacy_thresh_env else hard_threshold

    return Settings(
        cache_threshold=legacy_threshold,
        cache_hard_threshold=hard_threshold,
        cache_soft_threshold=soft_threshold,
        db_path=os.getenv("TOKENSHIELD_DB_PATH", ".tokenshield/tokenshield.sqlite3"),
        embedding_backend=os.getenv("TOKENSHIELD_EMBEDDING_BACKEND", "hash"),
        providers=providers,
    )
