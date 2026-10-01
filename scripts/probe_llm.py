"""Endpoint doctor for the LLM chain: config -> /models -> tiny chat call.

Run from the repo root:

    python scripts/probe_llm.py                # use LLM_* from .env / env
    python scripts/probe_llm.py --model NAME   # override the model for the call

The script never writes anything and never prints the full API key. It
answers, in order, the three questions every "translations failed" report
boils down to:

1. What does the pipeline SEE?  (base URL, model, masked key from .env)
2. Is the endpoint reachable, and does the key authenticate?  (GET /models)
3. Does the FULL chain work - including the upstream credentials a local
   router such as 9Router attaches before calling the real provider?
   (one minimal chat completion)

Every common failure is translated into the fix that actually unblocks it,
for example: OpenRouter's "Missing Authentication header" relayed by
9Router means the OpenRouter connection inside the 9Router dashboard has
no API key - not that the Python pipeline forgot its header.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp
from dotenv import load_dotenv

import os

LINE = "-" * 62


def _mask(key: str) -> str:
    if len(key) <= 10:
        return f"{key[:2]}...{key[-2:]}"
    return f"{key[:6]}...{key[-4:]}"


def _is_local(url: str) -> bool:
    return any(m in url for m in ("//localhost", "//127.0.0.1", "//[::1]", "//0.0.0.0"))


def _body_head(text: str, limit: int = 220) -> str:
    return " ".join(text.split())[:limit]


def interpret(status: int, body: str, url: str) -> list[str]:
    """Turn a failure into plain-language fixes, most likely first."""
    hints: list[str] = []
    lowered = body.lower()

    if "missing authentication header" in lowered:
        hints.append(
            "OpenRouter received the request with NO key. If this endpoint is "
            "9Router: open the dashboard -> Providers -> OpenRouter -> edit the "
            "connection -> paste a real OpenRouter API key (sk-or-v1-... from "
            "openrouter.ai/settings/keys) -> save, then re-run this probe."
        )
    if "invalid api key" in lowered or "invalid_api_key" in lowered:
        hints.append(
            "The router itself rejected YOUR key. Copy the router's own API key "
            "(9Router: dashboard -> API keys) into LLM_API_KEY in .env - a provider "
            "key (sk-or-...) does not belong there."
        )
    if "missing api key" in lowered:
        hints.append(
            "The router requires an API key but saw none. Set LLM_API_KEY in .env "
            "to the router's own key and re-run."
        )
    if "no active credentials" in lowered:
        hints.append(
            "The router has no ACTIVE connection for the provider this model routes "
            "to. Add/activate the provider account in the router dashboard."
        )
    if "invalid model" in lowered or "model not found" in lowered or "no endpoints" in lowered:
        hints.append(
            "LLM_MODEL is unknown to this endpoint. Pick an id from the /models "
            "list above (or a combo name) and set it as LLM_MODEL in .env."
        )
    if status == 429:
        hints.append(
            "Rate limit on the upstream account - the chain works; wait for the "
            "reset or add another provider account in the router."
        )
    if status in (401, 403) and not _is_local(url):
        hints.append(
            "The endpoint rejected the key outright - re-copy the RAW key "
            "(no 'Bearer ', no quotes, no spaces)."
        )
    return hints


def _print_hints(status: int, body: str, url: str) -> None:
    for hint in interpret(status, body, url):
        print(f"  >> {hint}")


async def _get_models(session: aiohttp.ClientSession, url: str, key: str) -> bool:
    print(f"\n[2/3] GET {url}/models")
    try:
        async with session.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"}) as r:
            text = await r.text()
    except aiohttp.ClientError as error:
        print(f"  FAIL network: {error!r}")
        print("  >> endpoint unreachable - is the router running? "
              "(9Router serves http://localhost:20128/v1)")
        return False
    if r.status != 200:
        print(f"  FAIL HTTP {r.status}: {_body_head(text)}")
        _print_hints(r.status, text, url)
        return False
    try:
        ids = [m.get("id", "") for m in json.loads(text).get("data", [])]
    except (json.JSONDecodeError, AttributeError):
        print(f"  WARN HTTP 200 but non-JSON/unknown shape: {_body_head(text)}")
        print("  >> a non-JSON reply means something OTHER than an OpenAI-compatible "
              "router is listening on this port, or the base URL path is wrong "
              "(it should end in /v1)")
        return False
    print(f"  OK {len(ids)} models visible with this key")
    for model_id in ids[:25]:
        print(f"    - {model_id}")
    if len(ids) > 25:
        print(f"    ... and {len(ids) - 25} more")
    if not ids:
        print("  >> empty list: no provider connection is active in the router yet")
    return True


async def _chat_call(
    session: aiohttp.ClientSession, url: str, key: str, model: str
) -> bool:
    print(f"\n[3/3] POST {url}/chat/completions  (model={model!r})")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 16,
        "stream": False,
    }
    try:
        async with session.post(
            f"{url}/chat/completions", json=payload,
            headers={"Authorization": f"Bearer {key}"},
        ) as r:
            text = await r.text()
    except aiohttp.ClientError as error:
        print(f"  FAIL network: {error!r}")
        return False
    if r.status != 200:
        print(f"  FAIL HTTP {r.status}: {_body_head(text)}")
        _print_hints(r.status, text, url)
        return False
    try:
        content = json.loads(text)["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        print(f"  WARN HTTP 200 but unexpected shape: {_body_head(text)}")
        return False
    print(f"  OK reply: {content!r:.60}")
    return True


async def run(args: argparse.Namespace) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    base_url = os.getenv("LLM_BASE_URL", "https://api.b.ai/v1").rstrip("/")
    key = os.getenv("LLM_API_KEY", "")
    model = args.model or os.getenv("LLM_MODEL", "(unset)")
    provider = os.getenv("LLM_PROVIDER", "glm")

    print(f"{LINE}\n[1/3] effective config (from .env / environment)\n{LINE}")
    print(f"  LLM_PROVIDER : {provider}")
    print(f"  LLM_BASE_URL : {base_url}")
    print(f"  LLM_MODEL    : {model}")
    print(f"  LLM_API_KEY  : {_mask(key) if key else '(EMPTY - set it in .env)'}")
    print(f"  chat URL     : {base_url}/chat/completions")
    if not key:
        print("\nBLOCKED at step 1: no key -> the pipeline cannot authenticate anywhere.")
        return 2
    if args.model:
        model = args.model

    timeout = aiohttp.ClientTimeout(total=45)
    ok_models = False
    ok_chat = False
    async with aiohttp.ClientSession(timeout=timeout) as session:
        ok_models = await _get_models(session, base_url, key)
        if model == "(unset)":
            print("\n[3/3] SKIPPED: LLM_MODEL is not set - pick one from the list above.")
        else:
            ok_chat = await _chat_call(session, base_url, key, model)

    print(f"\n{LINE}\nsummary\n{LINE}")
    if ok_chat:
        print("PASS: the endpoint works END TO END (auth + upstream provider). "
              "The backfill can use it as-is.")
        return 0
    if ok_models:
        print("PARTIAL: key authenticates, but the chat call fails - read the "
              "hint above; it is a router/upstream configuration issue.")
        return 1
    print("FAIL: the endpoint is unusable as configured - read the hints above.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the LLM endpoint end to end")
    parser.add_argument("--model", type=str, default=None,
                        help="override LLM_MODEL for the chat test")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
