"""Turn the saved tcgcsv files into data/prices.json: one record per card product.

Run order:  fetching/fetch_prices.py  ->  extracting/extract_prices.py

The saved CSVs have one row per product and printing. This groups the rows by product, so each
record looks like:

    {
      "product_id": 42346,
      "group_id": 604,
      "group_name": "Base Set",
      "name": "Alakazam",
      "number": "001/102",
      "rarity": "Holo Rare",
      "url": "https://cpt.tcgcsv.com/XXl",
      "image_url": "https://tcgplayer-cdn.tcgplayer.com/product/42346_200w.jpg",
      "prices": [{"sub_type": "Holofoil", "market": 70.81, "low": 43.5, "mid": 56.33,
                  "high": 9999.0, "direct_low": 54.51}]
    }

Sealed products have no card number (the extNumber column is empty) and are skipped.
This stage does not interpret the data (no name cleaning, no matching); merge_prices.py does that.
"""
import csv
import json
import re
from pathlib import Path

CSV_NAME = "ProductsAndPrices.csv"


def read_json_results(path):
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("results") or []


def read_rows(path):
    """The rows of a saved ProductsAndPrices.csv as dicts ([] if the file is missing or empty)."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:  # newline="" keeps quoted line breaks
        return list(csv.DictReader(file))


def to_float(text):
    """'43.5' -> 43.5, '' -> None."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def number_from_name(name):
    """Fallback when extNumber is empty: a 'Name - 139/195' suffix on the product name."""
    match = re.search(r"-\s+([A-Za-z0-9/\-]*\d[A-Za-z0-9/\-]*)\s*$", name)
    return match.group(1) if match else None


def price_row(row):
    """The price columns of a CSV row, or None if the row has no price (e.g. an unlisted card)."""
    values = {
        "market": to_float(row.get("marketPrice")),
        "low": to_float(row.get("lowPrice")),
        "mid": to_float(row.get("midPrice")),
        "high": to_float(row.get("highPrice")),  # often meaningless (sellers "park" absurd prices)
        "direct_low": to_float(row.get("directLowPrice")),
    }
    if all(value is None for value in values.values()):
        return None
    return {"sub_type": row.get("subTypeName") or None, **values}


def build_json(data_dir="data"):
    raw_dir = Path(data_dir) / "tcgcsv"
    groups_path = raw_dir / "groups.json"
    if not groups_path.exists():
        raise SystemExit(f"{groups_path} not found. Run fetching/fetch_prices.py first.")

    snapshot_path = raw_dir / "last_updated.txt"
    snapshot = snapshot_path.read_text(encoding="utf-8").strip() if snapshot_path.exists() else None

    records = []
    sealed = 0
    stale_groups = []
    unfetched_groups = []

    for group in read_json_results(groups_path):
        group_id = group["groupId"]
        folder = raw_dir / str(group_id)
        if not (folder / "_snapshot").exists():
            unfetched_groups.append(group["name"])
            continue
        if snapshot and (folder / "_snapshot").read_text(encoding="utf-8").strip() != snapshot:
            stale_groups.append(group["name"])

        by_product = {}  # one record per product; its printings become the "prices" list
        for row in read_rows(folder / CSV_NAME):
            number = (row.get("extNumber") or "").strip() or number_from_name(row.get("name", ""))
            if not number:
                sealed += 1
                continue
            product_id = int(row["productId"])
            record = by_product.get(product_id)
            if record is None:
                record = by_product[product_id] = {
                    "product_id": product_id,
                    "group_id": group_id,
                    "group_name": group["name"],
                    "name": row["name"],
                    "number": number,
                    "rarity": (row.get("extRarity") or "").strip() or None,
                    "url": row.get("url") or None,
                    "image_url": row.get("imageUrl") or None,
                    "prices": [],
                }
            price = price_row(row)
            if price:
                record["prices"].append(price)
        records.extend(by_product.values())

    out_path = Path(data_dir) / "prices.json"
    out_path.write_text(
        json.dumps({"snapshot": snapshot, "products": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with_prices = sum(1 for r in records if r["prices"])
    print(f"{len(records)} card products ({with_prices} with prices), {sealed} sealed rows skipped -> {out_path}")
    print(f"mirror snapshot: {snapshot}")
    if unfetched_groups:
        print(f"{len(unfetched_groups)} groups not fetched yet: {unfetched_groups[:5]}")
    if stale_groups:
        print(f"{len(stale_groups)} groups from an older snapshot: {stale_groups[:5]}")
    return records


if __name__ == "__main__":
    build_json()