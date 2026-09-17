from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import ProviderConfig


class ProviderError(Exception):
    def __init__(self, provider: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class ProviderResult(tuple):
    """
    3-tuple compatible result (response, provider, used_failover)
    with .attempts attribute holding chronological attempt logs:
    [{"provider": "...", "status": 403}, {"provider": "...", "status": 200}]
    """
    response: dict[str, Any]
    provider: ProviderConfig
    used_failover: bool
    attempts: list[dict[str, Any]]

    def __new__(
        cls,
        response: dict[str, Any],
        provider: ProviderConfig,
        used_failover: bool,
        attempts: list[dict[str, Any]] | None = None,
    ):
        instance = super().__new__(cls, (response, provider, used_failover))
        instance.response = response
        instance.provider = provider
        instance.used_failover = used_failover
        instance.attempts = attempts or []
        return instance


class ProviderRouter:
    def __init__(
        self,
        providers: tuple[ProviderConfig, ...],
        post_func: Callable[[ProviderConfig, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.providers = providers
        self._post_func = post_func
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def chat_completion(self, payload: dict[str, Any]) -> ProviderResult:
        failures: list[str] = []
        attempts: list[dict[str, Any]] = []
        configured = [provider for provider in self.providers if provider.configured]
        if not configured:
            raise ProviderError("none", 401, "No provider API keys are configured.")

        for index, provider in enumerate(configured):
            next_payload = dict(payload)
            next_payload["model"] = provider.model
            try:
                response = await self._post_provider(provider, next_payload)
                attempts.append({"provider": provider.name, "status": 200})
                return ProviderResult(response, provider, index > 0, attempts=attempts)
            except ProviderError as error:
                attempts.append({"provider": provider.name, "status": error.status_code})
                failures.append(f"{provider.name}:{error.status_code}")
                if error.status_code not in {402, 403, 408, 409, 425, 429, 500, 502, 503, 504}:
                    raise

        raise ProviderError("all", 502, f"All configured providers failed: {', '.join(failures)}")

    async def _post_provider(self, provider: ProviderConfig, payload: dict[str, Any]) -> dict[str, Any]:
        if self._post_func is not None:
            return await self._post_func(provider, payload)

        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "TokenShield",
        }
        client = self._get_client()
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=45.0)
        except httpx.TimeoutException as exc:
            raise ProviderError(provider.name, 504, f"Request timed out after 45s: {exc}") from exc
        except httpx.NetworkError as exc:
            raise ProviderError(provider.name, 502, f"Network connection failed: {exc}") from exc
        except Exception as exc:
            raise ProviderError(provider.name, 500, f"Unexpected request failure: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(provider.name, response.status_code, response.text[:500])

        try:
            return response.json()
        except Exception as exc:
            raise ProviderError(provider.name, 502, f"Invalid JSON response from provider: {exc}") from exc
