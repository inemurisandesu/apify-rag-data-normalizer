"""Apify Actor entry point with Pay-Per-Event charging support."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .normalizer import process_documents


async def run_actor() -> None:
    from apify import Actor

    async with Actor:
        actor_input: dict[str, Any] = await Actor.get_input() or {}
        documents = actor_input.get("documents") or []
        chunk_size = int(actor_input.get("chunkSize", 800))
        chunk_overlap = int(actor_input.get("chunkOverlap", 100))
        redact_pii_flag = bool(actor_input.get("redactPii", True))
        deduplicate_flag = bool(actor_input.get("deduplicate", True))

        if not documents:
            Actor.log.warning("No documents supplied in input.")
            await Actor.set_value("SUMMARY", {"inputDocuments": 0, "outputChunks": 0})
            return

        chunks, stats = process_documents(
            documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            do_redact_pii=redact_pii_flag,
            deduplicate=deduplicate_flag,
        )

        # Charge per normalized chunk when Pay-Per-Event is configured in Apify Console.
        for chunk in chunks:
            await Actor.push_data(chunk.to_dict(), charged_event_name="normalized-chunk")

        await Actor.set_value("SUMMARY", stats)
        Actor.log.info(f"Completed normalization: {json.dumps(stats, ensure_ascii=False)}")


def run_local_cli(input_path: Path) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    chunks, stats = process_documents(
        payload.get("documents", []),
        chunk_size=int(payload.get("chunkSize", 800)),
        chunk_overlap=int(payload.get("chunkOverlap", 100)),
        do_redact_pii=bool(payload.get("redactPii", True)),
        deduplicate=bool(payload.get("deduplicate", True)),
    )
    print(json.dumps({"summary": stats, "chunks": [c.to_dict() for c in chunks]}, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--local-input":
        raise SystemExit(run_local_cli(Path(sys.argv[2])))
    asyncio.run(run_actor())
