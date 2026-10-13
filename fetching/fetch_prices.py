"""Download Pokémon card prices from tcgcsv.com into data/tcgcsv/.

Run order:  fetching/fetch_prices.py  ->  extracting/extract_prices.py  ->  merge_prices.py
Requires:   pip install requests

tcgcsv.com mirrors TCGplayer's catalog and prices, refreshed once a day (around 20:00 UTC).

    https://tcgcsv.com/tcgplayer/3/groups                        every group in category 3 (Pokémon)
    https://tcgcsv.com/tcgplayer/3/<groupId>/ProductsAndPrices.csv   one group's products joined with
                                                                 their prices: one row per product
                                                                 and printing
    https://tcgcsv.com/last-updated.txt                          when the mirror was last refreshed

A group is roughly one expansion (groupId 604 is the number in .../604/ProductsAndPrices.csv).
The CSV has columns such as productId, name, extNumber, extRarity, lowPrice, midPrice, highPrice,
marketPrice, directLowPrice and subTypeName. Which ext* columns exist varies from group to group.

Saved as:
    data/tcgcsv/groups.json, last_updated.txt
    data/tcgcsv/<groupId>/ProductsAndPrices.csv, _snapshot

Resuming: a group is skipped if its _snapshot file holds the mirror's current last-updated
value. When the mirror refreshes (the next day), every group is downloaded again.
"""
import csv
import io
import json
import time
from pathlib import Path

import requests

BASE = "https://tcgcsv.com/tcgplayer"
LAST_UPDATED_URL = "https://tcgcsv.com/last-updated.txt"
CATEGORY = 3  # Pokémon (English). 85 is Pokémon Japan.
CSV_NAME = "ProductsAndPrices.csv"

# The site asks for a clearly identifiable User-Agent. Put your contact in it.
USER_AGENT = "bulbapedia-search-project/0.1 (contact: you@example.com)"
DELAY = 0.5  # seconds between requests; the site's own example uses 0.25

OUT_DIR = Path("data") / "tcgcsv"


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def get(session, url, delay=DELAY):
    """GET a url with retries. Returns None for a 404 (a group with no products has no file)."""
    for attempt in range(5):
        response = session.get(url, timeout=60)
        if response.status_code == 404:
            time.sleep(delay)
            return None
        if response.status_code in (429, 500, 502, 503, 504):
            wait = 5 * 2 ** attempt
            print(f"    HTTP {response.status_code} from {url}, waiting {wait}s", flush=True)
            time.sleep(wait)
            continue
        response.raise_for_status()
        time.sleep(delay)
        return response
    raise RuntimeError(f"{url} kept failing")


def row_count(content):
    """Number of data rows in a CSV (fields can contain line breaks, so lines are not rows)."""
    text = content.decode("utf-8-sig")
    return sum(1 for _ in csv.DictReader(io.StringIO(text, newline="")))


def fetch_group(session, group, snapshot, out_dir, delay):
    group_id = group["groupId"]
    group_dir = out_dir / str(group_id)
    group_dir.mkdir(parents=True, exist_ok=True)

    response = get(session, f"{BASE}/{CATEGORY}/{group_id}/{CSV_NAME}", delay)
    content = response.content if response is not None else b""
    # Bytes, not text, so line breaks inside quoted fields (card text) are kept exactly.
    (group_dir / CSV_NAME).write_bytes(content)

    # Written last, so a group interrupted halfway is fetched again next time.
    (group_dir / "_snapshot").write_text(snapshot, encoding="utf-8")
    return row_count(content) if content else 0


def fetch_all(out_dir=OUT_DIR, session=None, delay=DELAY, max_groups=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or make_session()

    snapshot = get(session, LAST_UPDATED_URL, delay).text.strip()
    print(f"mirror last updated: {snapshot}")

    groups_response = get(session, f"{BASE}/{CATEGORY}/groups", delay)
    groups = groups_response.json()["results"]
    (out_dir / "groups.json").write_text(groups_response.text, encoding="utf-8")
    (out_dir / "last_updated.txt").write_text(snapshot, encoding="utf-8")
    print(f"{len(groups)} groups")

    fetched = skipped = 0
    for number, group in enumerate(groups[:max_groups], 1):
        marker = out_dir / str(group["groupId"]) / "_snapshot"
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == snapshot:
            skipped += 1
            continue
        rows = fetch_group(session, group, snapshot, out_dir, delay)
        fetched += 1
        print(f"  [{number}/{len(groups)}] {group['groupId']} {group['name']}: {rows} rows", flush=True)

    print(f"done: {fetched} groups fetched, {skipped} already up to date")


if __name__ == "__main__":
    fetch_all()