#!/usr/bin/env python3
"""Extract the public Pokémon card catalogue from TCG API.

The API quota is tracked per key. Three keys can therefore be used safely in
round-robin order, while every request and response remains reproducible in
the raw JSONL output without writing credentials to disk.

The TCGAPI_KEY_*index* has to be exported as env. variable
export TCGAPI_KEY_1="tcg_live_9fb34fb743046412d3d6f00b7f548e1d8e8dd134"
export TCGAPI_KEY_2="tcg_live_8a5dde965304745f408c681749315f6098f9c16d"
export TCGAPI_KEY_3="tcg_live_9518afba9b4f28c97232c5953f81e8365becdbef"

remember, only 100 requests per day
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.tcgapi.dev/v1"
DEFAULT_OUTPUT = Path("data/raw/tcgapi_pokemon_cards.jsonl")
DEFAULT_METADATA = Path("data/raw/tcgapi_pokemon_cards_metadata.json")
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Pokémon sets and cards from TCG API."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--max-sets", type=int, default=None)
    parser.add_argument("--sets-page", type=int, default=1)
    parser.add_argument("--sets-pages", type=int, default=None)
    return parser.parse_args()


def api_keys() -> list[str]:
    keys = [
        os.environ.get(f"TCGAPI_KEY_{index}", "").strip()
        for index in range(1, 4)
    ]
    configured = [key for key in keys if key]
    if not configured:
        raise RuntimeError(
            "No TCG API key configured. Set TCGAPI_KEY_1, "
            "TCGAPI_KEY_2, or TCGAPI_KEY_3."
        )
    return configured


def response_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("TCG API response did not contain a list of records")


def response_total(payload: Any, item_count: int) -> int:
    if isinstance(payload, dict):
        for container in (payload, payload.get("meta", {})):
            if isinstance(container, dict):
                for key in ("total", "total_count", "count"):
                    if isinstance(container.get(key), int):
                        return container[key]
    return item_count


class KeyPool:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self._index = 0
        self.usage: Counter[int] = Counter()

    def next(self) -> tuple[int, str]:
        index = self._index % len(self._keys)
        self._index += 1
        self.usage[index] += 1
        return index, self._keys[index]


def get_json(
    path: str,
    query: dict[str, Any],
    *,
    base_url: str,
    key_pool: KeyPool,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> tuple[Any, int]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}?{urlencode(query)}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        key_index, key = key_pool.next()
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "PRI-tcgapi-extractor/1.0",
                "X-API-Key": key,
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")), key_index
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(retry_delay * (attempt + 1))
    raise RuntimeError(f"TCG API request failed for {url}: {last_error}") from last_error


def main() -> int:
    args = parse_args()
    if args.page_size < 1 or args.timeout < 1 or args.retries < 0:
        raise ValueError("page-size and timeout must be positive; retries cannot be negative")
    if args.max_sets is not None and args.max_sets < 1:
        raise ValueError("max-sets must be positive")
    if args.sets_page < 1 or (args.sets_pages is not None and args.sets_pages < 1):
        raise ValueError("sets-page and sets-pages must be positive")

    pool = KeyPool(api_keys())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    sets: list[dict[str, Any]] = []
    set_pages = 0

    requested_pages = args.sets_pages
    page = args.sets_page
    while requested_pages is None or set_pages < requested_pages:
        payload, _ = get_json(
            "/games/pokemon/sets",
            {"page": page, "per_page": args.page_size},
            base_url=args.base_url,
            key_pool=pool,
            timeout=args.timeout,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
        page_items = response_items(payload)
        sets.extend(page_items)
        set_pages += 1
        print(f"Sets page {page}: {len(page_items)} records")
        total = response_total(payload, len(page_items))
        if not page_items or len(sets) >= total or len(page_items) < args.page_size:
            break
        page += 1

    if args.max_sets is not None:
        sets = sets[: args.max_sets]

    card_count = 0
    failed_sets: list[dict[str, str]] = []
    with args.output.open("w", encoding="utf-8") as output:
        for set_index, set_record in enumerate(sets):
            set_id = set_record.get("id") or set_record.get("_id")
            if not set_id:
                failed_sets.append({"reason": "set has no id", "set": str(set_record)})
                continue
            try:
                payload, _ = get_json(
                    f"/sets/{set_id}/cards",
                    {},
                    base_url=args.base_url,
                    key_pool=pool,
                    timeout=args.timeout,
                    retries=args.retries,
                    retry_delay=args.retry_delay,
                )
                cards = response_items(payload)
            except RuntimeError as error:
                failed_sets.append({"set_id": str(set_id), "error": str(error)})
                print(f"Set {set_id} failed: {error}")
                continue
            for card_index, card in enumerate(cards):
                output.write(
                    json.dumps(
                        {
                            "source": "tcgapi",
                            "game": "pokemon",
                            "set_id": set_id,
                            "set": set_record,
                            "card_index": card_index,
                            "card": card,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            card_count += len(cards)
            print(f"Set {set_index + 1}/{len(sets)} {set_id}: {len(cards)} cards")

    metadata = {
        "source": "TCG API",
        "game": "pokemon",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "sets_pages": set_pages,
        "sets_requested": len(sets),
        "cards_written": card_count,
        "failed_sets": failed_sets,
        "key_usage": {
            f"TCGAPI_KEY_{index + 1}": count
            for index, count in sorted(pool.usage.items())
        },
        "note": "Keys are rotated per request; key values are never written to output.",
    }
    args.metadata.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {card_count} cards to {args.output}")
    return 0 if not failed_sets else 2


if __name__ == "__main__":
    raise SystemExit(main())
