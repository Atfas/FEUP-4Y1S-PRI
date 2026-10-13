"""Merge TCGplayer market prices into the search-ready cards.

Run order:  build_search_data.py  ->  merge_prices.py
Reads:      data/search/cards.json   (from build_search_data.py)
            data/prices.json         (from extracting/extract_prices.py)
Writes:     data/search/cards.json   (updated in place; running this twice gives the same result)
            data/search/price_report.json

Each print of a card gets a "prices" list, one entry per TCGplayer product and printing:

    {"product_id": 123, "product_name": "Abra - 063/165", "sub_type": "Reverse Holofoil",
     "market": 0.25, "low": 0.1, "mid": 0.3, "direct_low": null, "url": "...", "match": "name_number"}

and each card gets market_price_min, market_price_max and price_updated, which are handy for
filtering and sorting ("cards under $5"). "high" prices are left out because sellers park absurd
listings there.

How products are matched to cards
---------------------------------
TCGplayer names its sets differently from Bulbapedia ("SWSH12: Silver Tempest" vs "Silver Tempest"),
so the group names are not used. A product is matched on its card name and printed number instead:

  1. name_number: same cleaned name and same number ("Abra - 063/165" -> Abra, 63/165).
     Leading zeros and accents are ignored. A card is known by two names, its infobox name
     ("Flareon") and its page-title name with the suffix ("Flareon ex").
  2. If that matches several prints, the one in the group's expansion wins. A group's expansion is
     inferred by voting: whichever expansion most of its products match.
  3. number_only: if nothing matched by name, the group's expansion is known, and exactly one print
     there has that number, it is used when one name's words are all in the other ("Mew" / "Mew ex").

Anything still ambiguous or unmatched is left out and listed in the report, never guessed.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from processing.process_cards import normalize  # same name matching as the rest of the pipeline

DATA_DIR = Path("data")
SEARCH_DIR = Path("search")
MIN_GROUP_VOTES = 3  # a group needs this many matching products before its expansion is trusted


# ---------- names and numbers ----------
def clean_name(product_name):
    """TCGplayer product name -> card name: 'Mewtwo - 010/165' -> 'Mewtwo', 'Eevee (Prerelease)' -> 'Eevee'."""
    name = re.sub(r"\s+-\s+[^-]*\d[^-]*$", "", product_name)  # " - 010/165", " - SWSH039"
    while True:
        stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # trailing "(...)" notes
        if stripped == name:
            return name.strip()
        name = stripped


def norm_number(number):
    """'063/165' -> '63/165', 'SWSH039' -> 'swsh39': lower case, no spaces, no leading zeros."""
    text = str(number).lower().replace(" ", "")
    return re.sub(r"\d+", lambda match: str(int(match.group())), text)


def numerator(number):
    return norm_number(number).split("/")[0]


def names_compatible(a, b):
    """True if all the words of the shorter name appear in the longer one.

    'mew' fits 'mew ex' but not 'mewtwo'; 'professor s research' fits "Professor's Research [Magnolia]".
    """
    words_a, words_b = set(re.findall(r"\w+", a)), set(re.findall(r"\w+", b))
    if not words_a or not words_b:
        return False
    return words_a <= words_b or words_b <= words_a


def full_name(card):
    """The card name including its suffix, taken from the page title.

    Bulbapedia's infobox cardname leaves the suffix off ('Flareon'), but the page title keeps it:
    'Flareon ex (Prismatic Evolutions 146)' -> 'Flareon ex'. TCGplayer names include the suffix.
    """
    match = re.match(r"^(.*\S)\s+\([^()]*\)$", card["title"])
    return match.group(1) if match else card["name"]


def expansion_key(print_):
    return normalize(print_.get("expansion") or print_.get("deck_kit") or "")


# ---------- indexes over our own prints ----------
def build_indexes(cards):
    by_name_number = defaultdict(list)      # (name, full number) -> [(card, print)]
    by_expansion_number = defaultdict(list)  # (expansion, numerator) -> [(card, print)]
    for card in cards:
        for print_ in card["prints"]:
            print_["prices"] = []  # start clean, so a second run does not double up
            if not print_.get("card_number"):
                continue
            entry = (card, print_)
            for name in {normalize(card["name"]), normalize(full_name(card))}:
                by_name_number[(name, norm_number(print_["card_number"]))].append(entry)
            by_expansion_number[(expansion_key(print_), numerator(print_["card_number"]))].append(entry)
    return by_name_number, by_expansion_number


def infer_group_expansions(products, by_name_number):
    """{group id: expansion key}, from the expansion most of the group's products match."""
    votes = defaultdict(Counter)
    for product in products:
        key = (normalize(clean_name(product["name"])), norm_number(product["number"]))
        for _card, print_ in by_name_number.get(key, []):
            votes[product["group_id"]][expansion_key(print_)] += 1

    group_expansion = {}
    for group_id, counter in votes.items():
        expansion, count = counter.most_common(1)[0]
        if count >= MIN_GROUP_VOTES:
            group_expansion[group_id] = expansion
    return group_expansion


# ---------- matching ----------
def match_product(product, group_expansion, by_name_number, by_expansion_number):
    """-> (card, print, method) or (None, None, reason)."""
    name = normalize(clean_name(product["name"]))
    expansion = group_expansion.get(product["group_id"])

    candidates = by_name_number.get((name, norm_number(product["number"])), [])
    method = "name_number"
    if len(candidates) > 1 and expansion:
        narrowed = [c for c in candidates if expansion_key(c[1]) == expansion]
        if narrowed:
            candidates = narrowed

    if not candidates and expansion:
        method = "number_only"
        same_number = by_expansion_number.get((expansion, numerator(product["number"])), [])
        candidates = [
            c for c in same_number
            if names_compatible(name, normalize(c[0]["name"])) or names_compatible(name, normalize(full_name(c[0])))
        ]

    if len(candidates) == 1:
        card, print_ = candidates[0]
        return card, print_, method
    return None, None, "ambiguous" if candidates else "unmatched"


def price_entries(product, method):
    """One entry per printing of the product ('high' is dropped on purpose)."""
    entries = []
    for row in product["prices"]:
        entries.append({
            "product_id": product["product_id"],
            "product_name": product["name"],
            "sub_type": row["sub_type"],
            "market": row["market"],
            "low": row["low"],
            "mid": row["mid"],
            "direct_low": row["direct_low"],
            "url": product["url"],
            "match": method,
        })
    return entries


def merge():
    cards_path = SEARCH_DIR / "cards.json"
    prices_path = DATA_DIR / "prices.json"
    for path, hint in ((cards_path, "build_search_data.py"), (prices_path, "extracting/extract_prices.py")):
        if not path.exists():
            raise SystemExit(f"{path} not found. Run {hint} first.")

    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    prices = json.loads(prices_path.read_text(encoding="utf-8"))
    products = prices["products"]

    by_name_number, by_expansion_number = build_indexes(cards)
    group_expansion = infer_group_expansions(products, by_name_number)

    methods = Counter()
    unmatched_by_group = Counter()
    unmatched_examples = []
    ambiguous_examples = []
    matched_prints = set()

    for product in products:
        card, print_, outcome = match_product(product, group_expansion, by_name_number, by_expansion_number)
        if card is None:
            methods[outcome] += 1
            unmatched_by_group[product["group_name"]] += 1
            examples = ambiguous_examples if outcome == "ambiguous" else unmatched_examples
            if len(examples) < 20:
                examples.append(f"{product['group_name']}: {product['name']}")
            continue
        methods[outcome] += 1
        print_["prices"].extend(price_entries(product, outcome))
        matched_prints.add((card["id"], print_.get("card_number")))

    cards_with_prices = 0
    for card in cards:
        market = [row["market"] for p in card["prints"] for row in p["prices"] if row["market"] is not None]
        card["market_price_min"] = min(market) if market else None
        card["market_price_max"] = max(market) if market else None
        card["price_updated"] = prices.get("snapshot")
        cards_with_prices += bool(market)

    for print_ in (p for card in cards for p in card["prints"]):
        print_.pop("card_number", None)
    cards_path.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")

    groups = {p["group_id"]: p["group_name"] for p in products}
    total_prints = sum(1 for card in cards for p in card["prints"] if p.get("card_number"))
    prints_with_prices = sum(1 for card in cards for p in card["prints"] if p["prices"])

    report = {
        "snapshot": prices.get("snapshot"),
        "products": {"total": len(products), **dict(methods)},
        "groups": {
            "total": len(groups),
            "mapped_to_an_expansion": len(group_expansion),
            "unmapped": sorted(name for gid, name in groups.items() if gid not in group_expansion),
        },
        "prints": {"with_card_number": total_prints, "matched": len(matched_prints),
                   "with_prices": prints_with_prices},
        "cards": {"total": len(cards), "with_market_price": cards_with_prices},
        "unmatched_products_by_group": dict(unmatched_by_group.most_common(25)),
        "unmatched_examples": unmatched_examples,
        "ambiguous_examples": ambiguous_examples,
    }
    (SEARCH_DIR / "price_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"{len(products)} card products: " + ", ".join(f"{n} {m}" for m, n in methods.most_common()))
    print(f"{len(group_expansion)}/{len(groups)} groups mapped to an expansion")
    print(f"{cards_with_prices}/{len(cards)} cards have a market price "
          f"({prints_with_prices}/{total_prints} prints; {len(matched_prints)} matched a product)")
    print(f"details: {SEARCH_DIR / 'price_report.json'}")
    return report


if __name__ == "__main__":
    merge()