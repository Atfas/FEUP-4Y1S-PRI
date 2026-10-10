#!/usr/bin/env python3
"""Capture public PokémonMeta pages and JSON API responses."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


ORIGIN = "https://www.pokemonmeta.com"
DEFAULT_PAGES = (
    "/",
    "/tier-list/",
    "/top-decks/",
    "/cards/",
    "/deck-tester/",
    "/winrates/",
)
API_QUERIES = (
    ("/api/v1/articles", {"hidden[$ne]": "true", "sort": "-date"}),
    ("/api/v1/top-decks", {"sort": "-created", "rush[$ne]": "true"}),
    ("/api/v1/cards", {"aggregate": "search", "sort": "-rarity,-release"}),
    ("/api/v1/winrates", {"sort": "date"}),
    ("/api/v1/sets", {"limit": "0", "sort": "-release"}),
    ("/api/v1/deck-types", {"limit": "0", "sort": "name"}),
    ("/api/v1/engines", {"limit": "0"}),
    ("/api/v1/ranked-types", {"limit": "0"}),
    ("/api/v1/nav-tabs", {}),
    ("/api/v1/users", {"limit": "0"}),
)


def api_url(path: str, query: dict[str, str]) -> str:
    origin = urlparse(ORIGIN)
    return urlunparse((origin.scheme, origin.netloc, path, "", urlencode(query), ""))


def fetch_api(url: str) -> tuple[int, str, str]:
    request = Request(
        url,
        headers={"User-Agent": "PRI-public-data-extractor/1.0 (+research use)"},
    )
    with urlopen(request, timeout=60) as response:
        return (
            response.status,
            response.headers.get("content-type", ""),
            response.read().decode("utf-8"),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture public PokémonMeta pages and API responses."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/pokemonmeta_dynamic_data.jsonl"),
    )
    parser.add_argument("--wait", type=float, default=5.0)
    parser.add_argument("--pages", nargs="*", default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Skip page navigation and retrieve the public API collections only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.wait < 0:
        raise ValueError("--wait must be non-negative")
    if args.max_pages is not None and args.max_pages < 1:
        raise ValueError("--max-pages must be positive")
    pages = args.pages or [f"{ORIGIN}{path}" for path in DEFAULT_PAGES]
    pages = [url if url.startswith("http") else f"{ORIGIN}{url}" for url in pages]
    if args.max_pages is not None:
        pages = pages[: args.max_pages]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            user_agent="PRI-public-data-extractor/1.0 (+research use)"
        )
        page = context.new_page()
        for page_url in ([] if args.api_only else pages):
            responses: list[dict[str, object]] = []

            def capture(response: object) -> None:
                response_url = response.url  # type: ignore[attr-defined]
                parsed = urlparse(response_url)
                if parsed.netloc != urlparse(ORIGIN).netloc:
                    return
                if not (
                    "/api/" in parsed.path
                    or response.request.resource_type  # type: ignore[attr-defined]
                    in {"fetch", "xhr"}
                ):
                    return
                try:
                    body = response.text()  # type: ignore[attr-defined]
                    request = response.request  # type: ignore[attr-defined]
                    responses.append(
                        {
                            "url": response_url,
                            "resource_type": request.resource_type,
                            "content_type": response.headers.get("content-type"),
                            "status": response.status,  # type: ignore[attr-defined]
                            "request_method": request.method,
                            "request_body": request.post_data,
                            "response_body": body,
                        }
                    )
                except (OSError, PlaywrightError) as error:
                    responses.append({"url": response_url, "status": "error", "error": str(error)})

            page.on("response", capture)
            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(int(args.wait * 1000))
                page_text = page.locator("body").inner_text(timeout=5_000)
            except PlaywrightError as error:
                page_text = ""
                responses.append({"url": page_url, "status": "error", "error": str(error)})
            finally:
                page.remove_listener("response", capture)
            records.append(
                {
                    "source_url": page_url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "page_text": page_text,
                    "responses": responses,
                }
            )
            print(f"{page_url}: {len(responses)} structured responses")
        for path, query in API_QUERIES:
            try:
                count_url = api_url(path, {**query, "count": "true"})
                count_status, count_type, count_body = fetch_api(count_url)
                try:
                    total = int(json.loads(count_body))
                except (TypeError, ValueError, json.JSONDecodeError):
                    total = 0
                page_size = 1000
                page_total = max(1, (total + page_size - 1) // page_size)
                if total:
                    collection_urls = [count_url] + [
                        api_url(
                            path,
                            {**query, "limit": str(page_size), "page": str(page_number)},
                        )
                        for page_number in range(1, page_total + 1)
                    ]
                else:
                    # Some public endpoints do not implement count=true.
                    collection_urls = [count_url, api_url(path, {**query, "limit": "0"})]
                for collection_url in collection_urls:
                    status, content_type, body = (
                        (count_status, count_type, count_body)
                        if collection_url == count_url
                        else fetch_api(collection_url)
                    )
                    records.append(
                        {
                            "source_url": collection_url,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "page_text": "",
                            "responses": [
                                {
                                    "url": collection_url,
                                    "resource_type": "api-direct",
                                    "content_type": content_type,
                                    "status": status,
                                    "request_method": "GET",
                                    "request_body": None,
                                    "response_body": body,
                                }
                            ],
                        }
                    )
                print(f"{path}: {total} records across {page_total} pages")
            except (OSError, PlaywrightError) as error:
                records.append(
                    {
                        "source_url": api_url(path, query),
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "page_text": "",
                        "responses": [{"url": api_url, "status": "error", "error": str(error)}],
                    }
                )
        browser.close()

    with args.output.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} page records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
