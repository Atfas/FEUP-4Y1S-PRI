#!/usr/bin/env python3
"""Normalize PokémonMeta public API responses into separate JSONL files."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


def walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_body(body: Any) -> Any:
    if not isinstance(body, str):
        return body
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_response": body}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse PokémonMeta captures.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/pokemonmeta_dynamic_data.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    return parser.parse_args()


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> int:
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def stable_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("_id", "id", "slug", "url"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def items_from_body(body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "results", "items", "docs"):
            if isinstance(body.get(key), list):
                return body[key]
    return [body] if isinstance(body, dict) and body not in ({},) else []


def main() -> int:
    args = parse_args()
    pages = [json.loads(line) for line in args.input.open(encoding="utf-8")]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = {
        "articles": [],
        "top_decks": [],
        "cards": [],
        "winrates": [],
        "sets": [],
        "deck_types": [],
        "engines": [],
        "ranked_types": [],
        "nav_tabs": [],
        "users": [],
        "other_api": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in grouped}
    response_counts: dict[str, int] = {}

    for page in pages:
        for response in page.get("responses", []):
            if response.get("status") != 200:
                continue
            response_url = response.get("url", "")
            path = urlparse(response_url).path
            if "/api/v1/" not in path:
                continue
            endpoint = path.split("/api/v1/", 1)[1].split("/", 1)[0]
            endpoint_aliases = {
                "top-decks": "top_decks",
                "deck-types": "deck_types",
                "ranked-types": "ranked_types",
                "nav-tabs": "nav_tabs",
            }
            key = endpoint_aliases.get(endpoint, endpoint)
            if key not in grouped:
                key = "other_api"
            data = parse_body(response.get("response_body"))
            items = items_from_body(data)
            response_counts[key] = response_counts.get(key, 0) + len(items)
            for index, item in enumerate(items):
                item_id = stable_id(item)
                fingerprint = item_id or hashlib.sha256(
                    json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if fingerprint in seen[key]:
                    continue
                seen[key].add(fingerprint)
                grouped[key].append(
                    {
                        "source": "pokemonmeta",
                        "endpoint": key,
                        "source_url": page["source_url"],
                        "api_url": response_url,
                        "retrieved_at": page["retrieved_at"],
                        "record_index": index,
                        "record_id": item_id,
                        "data": item,
                    }
                )

    counts: dict[str, int] = {}
    for key, records in grouped.items():
        counts[f"pokemonmeta_{key}.jsonl"] = write_jsonl(
            args.output_dir / f"pokemonmeta_{key}.jsonl",
            records,
        )
    metadata = {
        "source": "PokémonMeta",
        "input": str(args.input),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "records_written": counts,
        "note": (
            "Each entity is normalized to one JSONL record and deduplicated by "
            "stable ID or content fingerprint. The raw capture remains unchanged."
        ),
        "response_item_counts": response_counts,
        "deduplication": "stable _id/id/slug/url, otherwise SHA-256 content fingerprint",
    }
    (args.output_dir / "pokemonmeta_parsing_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, count in counts.items():
        print(f"{name}: {count} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
