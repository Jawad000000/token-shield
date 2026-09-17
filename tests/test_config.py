from app.config import indexed_provider_configs


def test_indexed_provider_configs_support_many_keys(monkeypatch) -> None:
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_1_NAME", "vercel-a")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_1_BASE_URL", "https://ai-gateway.vercel.sh/v1")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_1_API_KEY_ENV", "VERCEL_KEY_1")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_1_MODEL", "openai/gpt-5.5")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_2_NAME", "groq-a")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_2_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_2_API_KEY_ENV", "GROQ_KEY_1")
    monkeypatch.setenv("TOKENSHIELD_PROVIDER_2_MODEL", "llama-3.1-8b-instant")

    providers = indexed_provider_configs()

    assert [provider.name for provider in providers] == ["vercel-a", "groq-a"]
    assert providers[0].api_key_env == "VERCEL_KEY_1"
