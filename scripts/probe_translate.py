"""Diagnostic: one real translation call to see why multi-language JSON fails."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.llm.factory import make_provider
from src.llm.prompts import build_translation_messages

ENTRY = {
    "title": "Suspected sabotage causes major Netherlands rail disruption",
    "summary": (
        "A suspected act of sabotage has caused a major disruption to the "
        "Netherlands rail network, affecting train services and prompting an "
        "investigation. Authorities are treating the incident as potentially "
        "malicious rather than a routine technical failure."
    ),
    "take": (
        "When a railway goes down and the first instinct is to blame sabotage, "
        "it is a reminder that our physical infrastructure is still running on "
        "ancient plumbing. The grounded takeaway is that safety-critical "
        "systems need simple, observable, and resilient fallbacks."
    ),
}


async def main() -> None:
    load_dotenv()
    provider = make_provider()
    targets = ["fa", "fr", "de", "es", "zh"]
    try:
        reply = await provider.chat(
            build_translation_messages(ENTRY, targets), max_tokens=1800,
        )
    except Exception as error:  # noqa: BLE001 - diagnostic prints everything
        print(f"CALL FAILED: {error!r}")
        return
    print(f"reply length: {len(reply)} chars")
    print("--- head ---")
    print(reply[:300])
    print("--- tail ---")
    print(reply[-300:])
    try:
        start, end = reply.find("{"), reply.rfind("}")
        import json
        data = json.loads(reply[start: end + 1])
        print(f"parsed keys: {sorted(data)}")
    except Exception as error:  # noqa: BLE001
        print(f"PARSE FAILED: {error!r}")


if __name__ == "__main__":
    asyncio.run(main())
