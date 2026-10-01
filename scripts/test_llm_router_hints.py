"""Tests for the 401/403 auth hints and provider aliases (9Router support).

The pipeline ALWAYS attaches 'Authorization: Bearer <key>' (proven by
test_llm / apikey cleaning tests), so a 401 must be explained, not retried:
either the endpoint rejected the key, or - for a local router such as
9Router - the error is relayed from the upstream provider. OpenRouter's
relayed signature ('Missing Authentication header', numeric code) must map
to the dashboard fix, and LLM_PROVIDER=9router must not crash the factory.

Run: python3 scripts/test_llm_router_hints.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.factory import make_provider
from src.llm.glm_provider import GLMProvider, _is_local_url, _mask_key

ROUTER_KEY = "sk-a44dbc3aab31ed74-gqn7dt-b311c0a4"


def test_mask_key() -> None:
    assert _mask_key(ROUTER_KEY) == "sk-a44...c0a4"
    assert _mask_key("short") == "s...t"[:5] or _mask_key("short").startswith("s")
    assert "sk-a44dbc3aab31ed74" not in _mask_key(ROUTER_KEY)  # never leaks
    print("PASS _mask_key (fingerprint only, full key never leaked)")


def test_is_local_url() -> None:
    assert _is_local_url("http://localhost:20128/v1/chat/completions")
    assert _is_local_url("http://127.0.0.1:20128/v1/chat/completions")
    assert not _is_local_url("https://openrouter.ai/api/v1/chat/completions")
    assert not _is_local_url("https://api.b.ai/v1/chat/completions")
    print("PASS _is_local_url (loopback vs remote endpoints)")


def test_auth_hint_local_401() -> None:
    provider = GLMProvider(
        api_key=ROUTER_KEY, base_url="http://localhost:20128/v1", model="m",
    )
    hint = provider._auth_hint(401)
    assert "WAS sent" in hint and "sk-a44...c0a4" in hint
    assert "router dashboard" in hint and "Missing Authentication" in hint
    assert hint not in (None, "")
    # a relayed OpenRouter-style body + hint stays one readable line
    message = f"HTTP 401: {{\"error\":{{\"message\":\"Missing Authentication header\",\"code\":401}}}}{hint}"
    assert "Missing Authentication header" in message and "hint:" in message
    print("PASS auth hint (local router 401 names the dashboard fix)")


def test_auth_hint_remote_401() -> None:
    provider = GLMProvider(
        api_key="0123abcd0123abcd", base_url="https://api.b.ai/v1", model="m",
    )
    hint = provider._auth_hint(401)
    assert "WAS sent" in hint and "re-copy" in hint
    assert provider._auth_hint(500) == "" and provider._auth_hint(429) == ""
    print("PASS auth hint (remote 401 says key was rejected; other statuses quiet)")


def test_factory_aliases() -> None:
    os.environ.update({
        "LLM_API_KEY": "k", "LLM_BASE_URL": "http://localhost:20128/v1",
        "LLM_MODEL": "any-model",
    })
    for name in ("9router", "9Router", "openai-compatible", "openai", "glm"):
        os.environ["LLM_PROVIDER"] = name
        provider = make_provider()
        assert isinstance(provider, GLMProvider), name
        assert provider.url == "http://localhost:20128/v1/chat/completions"
    os.environ["LLM_PROVIDER"] = "does-not-exist"
    try:
        make_provider()
    except ValueError as error:
        assert "9router" in str(error)  # aliases listed in the message
    else:
        raise AssertionError("unknown provider must still raise ValueError")
    os.environ["LLM_PROVIDER"] = "glm"
    print("PASS factory aliases (9router/openai-compatible build GLMProvider)")


if __name__ == "__main__":
    test_mask_key()
    test_is_local_url()
    test_auth_hint_local_401()
    test_auth_hint_remote_401()
    test_factory_aliases()
    print("\nAll router-hint tests passed.")
