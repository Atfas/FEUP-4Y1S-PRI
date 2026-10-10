#!/usr/bin/env python3
"""Normalize Trainer Hill browser captures into separate JSONL datasets."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Trainer Hill Dash captures.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/trainerhill_dynamic_data.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--export-dir", type=Path, default=Path("data/raw/trainerhill_exports"))
    return parser.parse_args()


def walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_response(body: Any) -> Any:
    if not isinstance(body, str):
        return body
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_response": body}


def response_records(page: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for response in page.get("dash_responses", []):
        if response.get("status") != 200:
            continue
        yield {
            "source_url": page["source_url"],
            "retrieved_at": page["retrieved_at"],
            "request": parse_response(response.get("request_body", "")),
            "response": parse_response(response.get("response_body", "")),
        }


def download_payloads(value: Any) -> Iterator[dict[str, str]]:
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, str) and (
            "filename" in value or value.get("type") or value.get("base64")
        ):
            content = data
            if value.get("base64"):
                try:
                    content = base64.b64decode(data).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    content = ""
            yield {
                "filename": str(value.get("filename", "")),
                "type": str(value.get("type", "")),
                "content": content,
            }
        for child in value.values():
            yield from download_payloads(child)
    elif isinstance(value, list):
        for child in value:
            yield from download_payloads(child)


def rows_from_content(content: str, content_type: str = "") -> Iterator[dict[str, Any]]:
    stripped = content.lstrip("\ufeff \t\r\n")
    if not stripped:
        return
    if "json" in content_type or stripped[:1] in "[{":
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            for row in parsed:
                if isinstance(row, dict):
                    yield row
            return
        if isinstance(parsed, dict):
            yield parsed
            return
    for row in csv.DictReader(io.StringIO(content)):
        if any(value not in (None, "") for value in row.values()):
            yield dict(row)


def is_matchup(value: Any) -> bool:
    return isinstance(value, dict) and {
        "deck1", "deck2", "total", "win_rate", "wins", "losses", "ties"
    }.issubset(value)


def component_text(value: Any) -> str:
    if isinstance(value, str | int | float):
        return str(value)
    if isinstance(value, dict):
        return component_text(value.get("props", {}).get("children", ""))
    if isinstance(value, list):
        return " ".join(component_text(item) for item in value)
    return ""


def table_rows(value: Any) -> Iterator[list[str]]:
    if isinstance(value, dict):
        if value.get("type") == "Tr":
            children = value.get("props", {}).get("children", [])
            cells = children if isinstance(children, list) else [children]
            yield [component_text(cell).strip() for cell in cells]
        for child in value.values():
            yield from table_rows(child)


def component_records(value: Any, source_url: str, retrieved_at: str) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        props = value.get("props")
        if isinstance(props, dict):
            component_id = props.get("id")
            children = props.get("children")
            if component_id is not None or value.get("type") in {"Tr", "Td", "Th"}:
                yield {
                    "source": "trainerhill",
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                    "component_type": value.get("type"),
                    "component_id": component_id,
                    "text": component_text(children),
                    "children": children,
                }
        for child in value.values():
            yield from component_records(child, source_url, retrieved_at)
    elif isinstance(value, list):
        for child in value:
            yield from component_records(child, source_url, retrieved_at)
    elif isinstance(value, list):
        for child in value:
            yield from table_rows(child)


def write_jsonl(path: Path, records: Iterator[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> int:
    args = parse_args()
    pages = [json.loads(line) for line in args.input.open(encoding="utf-8")]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    matchups: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    exports: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for page in pages:
        for record in response_records(page):
            for value in walk(record["response"]):
                if is_matchup(value):
                    key = tuple(value[field] for field in (
                        "deck1", "deck2", "total", "win_rate",
                        "wins", "losses", "ties",
                    ))
                    if key not in seen:
                        seen.add(key)
                        matchups.append({
                            "source": "trainerhill",
                            "source_url": record["source_url"],
                            "retrieved_at": record["retrieved_at"],
                            **value,
                        })
            for row in table_rows(record["response"]):
                if any(row):
                    tables.append({
                        "source": "trainerhill",
                        "source_url": record["source_url"],
                        "retrieved_at": record["retrieved_at"],
                        "values": row,
                    })
            components.extend(
                component_records(
                    record["response"],
                    record["source_url"],
                    record["retrieved_at"],
                )
            )
            for payload in download_payloads(record["response"]):
                for row in rows_from_content(payload["content"], payload["type"]):
                    exports.append({
                        "source": "trainerhill",
                        "source_url": record["source_url"],
                        "retrieved_at": record["retrieved_at"],
                        "source_file": payload["filename"],
                        **row,
                    })

    for path in sorted(args.export_dir.iterdir()) if args.export_dir.exists() else []:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for row in rows_from_content(content):
            exports.append({"source": "trainerhill", "source_file": str(path), **row})

    def page_records(name: str) -> Iterator[dict[str, Any]]:
        for page in pages:
            if f"/{name}" in page["source_url"]:
                yield {
                    "source": "trainerhill",
                    "source_url": page["source_url"],
                    "retrieved_at": page["retrieved_at"],
                    "page_text": page.get("page_text", ""),
                    "dash_responses": list(response_records(page)),
                }

    counts = {
        "trainerhill_matchups.jsonl": write_jsonl(args.output_dir / "trainerhill_matchups.jsonl", iter(matchups)),
        "trainerhill_decks.jsonl": write_jsonl(args.output_dir / "trainerhill_decks.jsonl", page_records("decklist")),
        "trainerhill_cards.jsonl": write_jsonl(args.output_dir / "trainerhill_cards.jsonl", page_records("cards")),
        "trainerhill_meta.jsonl": write_jsonl(args.output_dir / "trainerhill_meta.jsonl", page_records("meta")),
        "trainerhill_table_rows.jsonl": write_jsonl(args.output_dir / "trainerhill_table_rows.jsonl", iter(tables)),
        "trainerhill_export_rows.jsonl": write_jsonl(args.output_dir / "trainerhill_export_rows.jsonl", iter(exports)),
        "trainerhill_components.jsonl": write_jsonl(args.output_dir / "trainerhill_components.jsonl", iter(components)),
    }
    metadata = {
        "source": "Trainer Hill",
        "input": str(args.input),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "records_written": counts,
        "date_ranges_seen": sorted({
            (
                parse_qs(urlparse(p.get("source_url", "")).query).get(
                    "start_date", [p.get("date_range", {}).get("start")]
                )[0],
                parse_qs(urlparse(p.get("source_url", "")).query).get(
                    "end_date", [p.get("date_range", {}).get("end")]
                )[0],
            )
            for p in pages if isinstance(p.get("date_range"), dict)
        }),
        "empty_matchup_capture": not matchups,
    }
    (args.output_dir / "trainerhill_parsing_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, count in counts.items():
        print(f"{name}: {count} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
