"""Sanity tests for the LLM_API_KEY preflight in GLMProvider.

Covers the exact paste mistakes that produce the provider-side
HTTP 401 "Invalid api_key format": edge whitespace/newlines and wrapping
quotes are cleaned automatically; Bearer prefixes, pasted env lines, and
internal whitespace must fail loudly instead of burning the daily run.

Run: python3 scripts/test_apikey_cleaning.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.glm_provider import GLMProvider, _validate_api_key

KEY = "0123abcd0123abcd0123abcd0123abcd"


def expect_ok(raw: str, cleaned: str) -> None:
    assert _validate_api_key(raw) == cleaned, raw


def expect_rejected(raw: str) -> None:
    try:
        _validate_api_key(raw)
    except ValueError as error:
        assert "api_key" in str(error), error
        return
    raise AssertionError(f"expected rejection: {raw!r}")


def main() -> None:
    # accepted as-is or after edge cleaning
    expect_ok(KEY, KEY)
    expect_ok(f"  {KEY}  ", KEY)          # edge spaces (shell/terminal copy)
    expect_ok(f"{KEY}\n", KEY)            # trailing newline (echo append)
    expect_ok(f'"{KEY}"', KEY)            # double-quoted paste
    expect_ok(f"'{KEY}'", KEY)            # single-quoted paste
    # structural paste mistakes must fail loudly before any HTTP call
    expect_rejected("")                   # empty secret
    expect_rejected("   ")                # whitespace-only secret
    expect_rejected(f"Bearer {KEY}")      # auth header pasted
    expect_rejected(f"BEARER {KEY}")      # case-insensitive prefix
    expect_rejected(f"LLM_API_KEY={KEY}")         # whole .env line
    expect_rejected(f"export LLM_API_KEY={KEY}")  # shell export line
    expect_rejected(f"LLM_API_KEY: {KEY}")        # YAML-style paste
    expect_rejected(f"{KEY[:10]} {KEY[10:]}")     # internal space
    expect_rejected(f"{KEY[:10]}\t{KEY[10:]}")    # internal tab
    # provider construction goes through the same preflight
    provider = GLMProvider(api_key=f"  {KEY}  ")
    assert provider.api_key == KEY
    try:
        GLMProvider(api_key=f"Bearer {KEY}")
    except ValueError:
        pass
    else:
        raise AssertionError("Bearer-prefixed key must be rejected in __init__")
    print("PASS api-key preflight: 5 cleaning cases + 9 rejection cases + __init__ wiring")


if __name__ == "__main__":
    main()
