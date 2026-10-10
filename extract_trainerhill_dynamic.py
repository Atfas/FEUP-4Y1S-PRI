#!/usr/bin/env python3
"""Capture public Trainer Hill Dash data loaded by the browser."""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


DEFAULT_SITEMAP = "https://www.trainerhill.com/sitemap.xml"
SITE_ORIGIN = "https://www.trainerhill.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture Trainer Hill browser-loaded data as JSONL."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/trainerhill_dynamic_data.jsonl"),
    )
    parser.add_argument("--wait", type=float, default=8.0)
    parser.add_argument("--sitemap", default=DEFAULT_SITEMAP)
    parser.add_argument("--pages", nargs="*", default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).date().isoformat(),
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path("data/raw/trainerhill_exports"),
    )
    parser.add_argument(
        "--window-years",
        type=int,
        default=1,
        help="Maximum historical window size in years; use 0 for one broad range.",
    )
    return parser.parse_args()


def sitemap_pages(sitemap_url: str) -> list[str]:
    request = Request(
        sitemap_url,
        headers={"User-Agent": "PRI-public-data-extractor/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        root = ElementTree.fromstring(response.read())
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        element.text.strip()
        for element in root.findall(".//sm:loc", namespace)
        if element.text and element.text.strip()
    ]


def trainerhill_url(url: str, start_date: str, end_date: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "game": "PTCG",
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    return urlunparse(parsed._replace(query=urlencode(query)))


def response_is_data(response: object) -> bool:
    response_url = response.url  # type: ignore[attr-defined]
    if not response_url.startswith(SITE_ORIGIN):
        return False
    if "_dash-update-component" in response_url:
        return True
    resource_type = response.request.resource_type  # type: ignore[attr-defined]
    content_type = response.headers.get("content-type", "").lower()  # type: ignore[attr-defined]
    return resource_type in {"fetch", "xhr"} and any(
        value in content_type for value in ("json", "csv", "text/plain")
    )


def date_windows(start: str, end: str, years: int) -> list[tuple[str, str]]:
    if years == 0:
        return [(start, end)]
    current = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    windows: list[tuple[str, str]] = []
    while current <= last:
        target_year = current.year + years
        target_month = current.month
        target_day = min(current.day, monthrange(target_year, target_month)[1])
        window_end = min(
            datetime(target_year, target_month, target_day).date() - timedelta(days=1),
            last,
        )
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end.fromordinal(window_end.toordinal() + 1)
    return windows


def main() -> int:
    args = parse_args()
    if args.wait < 0:
        raise ValueError("--wait must be non-negative")
    if args.max_pages is not None and args.max_pages < 1:
        raise ValueError("--max-pages must be positive")
    if args.window_years < 0:
        raise ValueError("--window-years cannot be negative")
    if args.start_date > args.end_date:
        raise ValueError("--start-date cannot be after --end-date")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.export_dir.mkdir(parents=True, exist_ok=True)
    pages = args.pages if args.pages else sitemap_pages(args.sitemap)
    pages = [page for page in pages if page.startswith(SITE_ORIGIN)]
    windows = date_windows(args.start_date, args.end_date, args.window_years)
    pages = [
        trainerhill_url(page, window_start, window_end)
        for window_start, window_end in windows
        for page in pages
    ]
    if args.max_pages is not None:
        pages = pages[: args.max_pages]

    records: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            user_agent="PRI-public-data-extractor/1.0 (+research use)"
        )
        page = context.new_page()
        for page_url in pages:
            print(f"Loading {page_url}")
            page_responses: list[dict[str, object]] = []

            def capture(response: object) -> None:
                if not response_is_data(response):
                    return
                try:
                    request = response.request  # type: ignore[attr-defined]
                    page_responses.append(
                        {
                            "url": response.url,  # type: ignore[attr-defined]
                            "resource_type": request.resource_type,
                            "content_type": response.headers.get("content-type"),
                            "status": response.status,  # type: ignore[attr-defined]
                            "request_body": request.post_data,
                            "response_body": response.text(),  # type: ignore[attr-defined]
                        }
                    )
                except PlaywrightError as error:
                    page_responses.append({"status": "error", "error": str(error)})

            page.on("response", capture)
            export_count = 0
            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(int(args.wait * 1000))
                page_text = page.locator("body").inner_text(timeout=5_000)
                controls = page.locator("button, a")
                for index in range(controls.count()):
                    control = controls.nth(index)
                    try:
                        label = control.inner_text(timeout=1_000).strip().lower()
                    except PlaywrightError:
                        continue
                    if not any(term in label for term in ("export", "download", "csv")):
                        continue
                    try:
                        with page.expect_download(timeout=5_000) as download_info:
                            control.click(timeout=5_000)
                        download = download_info.value
                        page_name = (
                            urlparse(page_url).path.strip("/").replace("/", "_")
                            or "home"
                        )
                        query = dict(parse_qsl(urlparse(page_url).query))
                        filename = (
                            f"{page_name}_{query.get('start_date', 'unknown')}_"
                            f"{query.get('end_date', 'unknown')}_{export_count}_"
                            f"{download.suggested_filename}"
                        )
                        download.save_as(str(args.export_dir / filename))
                        export_count += 1
                    except PlaywrightError:
                        continue
            except PlaywrightError as error:
                page_text = ""
                page_responses.append({"status": "error", "error": str(error)})
            finally:
                page.remove_listener("response", capture)

            records.append(
                {
                    "source_url": page_url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "page_text": page_text,
                    "dash_responses": page_responses,
                    "exports_downloaded": export_count,
                    "date_range": {
                        "start": dict(parse_qsl(urlparse(page_url).query)).get(
                            "start_date", args.start_date
                        ),
                        "end": dict(parse_qsl(urlparse(page_url).query)).get(
                            "end_date", args.end_date
                        ),
                    },
                }
            )
            print(
                f"Captured {len(page_responses)} structured responses, "
                f"{export_count} exports"
            )
        browser.close()

    with args.output.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} page records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
