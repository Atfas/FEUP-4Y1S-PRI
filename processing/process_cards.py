"""Build search-ready records from the extracted files.

Reads the extracted files (faithful to the wiki):
    cards.json, pokemon.json, artist.json, expansions.json
Writes the search-ready versions to OUT_DIR:
    cards.json, pokemon.json, artists.json, expansions.json, links_report.json

Cards, Pokémon, artists and expansions stay separate collections and point at each other by id.
The links are built from the card side only, so there is one source of truth: a card lists its
artists, Pokémon and expansions, and the entities get their card lists by reversing that.

Ids look like "card:abra-151-63", "pokemon:abra", "artist:mitsuhiro-arita", "expansion:151".
Names are matched ignoring case, accents and spacing. A name that a card uses but that has no
record (an artist without a page, say) gets a stub record with "has_page": false, so no link
ever points at nothing; the report lists every stub.

Standard library only.
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

EXTRACTED_DIR = Path("data")           # where the extracted json files are
OUT_DIR = Path("search")

FILE_PATH_URL = "https://bulbapedia.bulbagarden.net/wiki/Special:FilePath/"


# ---------- names and ids ----------
def normalize(name):
    """Key for matching names: no accents, lower case, single spaces, plain quotes."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def slugify(name):
    key = normalize(name).replace("\u2640", " female").replace("\u2642", " male")  # Nidoran
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "unnamed"


class Ids:
    """Hands out stable ids and remembers which name belongs to which id."""

    def __init__(self):
        self.by_name = {}      # (kind, normalized name) -> id
        self.taken = set()
        self.collisions = []   # names whose slug was already used by a different name

    def make(self, kind, name):
        key = (kind, normalize(name))
        if key in self.by_name:
            return self.by_name[key]
        base = f"{kind}:{slugify(name)}"
        candidate, number = base, 2
        while candidate in self.taken:
            if number == 2:
                self.collisions.append(name)
            candidate = f"{base}-{number}"
            number += 1
        self.taken.add(candidate)
        self.by_name[key] = candidate
        return candidate

    def find(self, kind, name):
        return self.by_name.get((kind, normalize(name)))


# ---------- small helpers ----------
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_first(*names):
    """Load the first of these files that exists in EXTRACTED_DIR."""
    for name in names:
        path = EXTRACTED_DIR / name
        if path.exists():
            return read_json(path)
    raise SystemExit(f"None of {names} found in {EXTRACTED_DIR}")


def to_int(value):
    """'150' -> 150. Anything else (None, '', '60+') -> None."""
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def image_url(filename):
    """Image link that needs no API call; the wiki redirects it to the real file."""
    return FILE_PATH_URL + quote(filename.replace(" ", "_"), safe="()_-.,'!&")


def flatten_blocks(blocks):
    """[{"heading", "text"}, ...] -> one string, with each heading on its own line."""
    parts = []
    for block in blocks:
        if block.get("heading"):
            parts.append(f"{block['heading']}\n{block['text']}")
        else:
            parts.append(block["text"])
    return "\n\n".join(parts)


def unique_names(names):
    """Drop repeats, treating names that normalize the same as one."""
    seen, result = set(), []
    for name in names:
        if name and normalize(name) not in seen:
            seen.add(normalize(name))
            result.append(name)
    return result


# ---------- card pieces ----------
def card_kind(raw):
    info = raw.get("infobox", {})
    if info.get("class"):
        return info["class"].lower()  # trainer, energy
    if raw.get("pokedex") or "species" in info or "hp" in info:
        return "pokemon"
    return "unknown"


def merge_prints(raw_prints, gallery, expansions):
    """Attach each gallery image and illustrator to the print of the same expansion.

    Gallery entries that match no print are kept as prints of their own, so nothing is lost.
    """
    unused = defaultdict(list)  # normalized expansion -> gallery entries not yet attached
    for entry in gallery:
        unused[normalize(entry.get("set") or "")].append(entry)

    prints = []
    for raw_print in raw_prints:
        merged = dict(raw_print)
        #print(merged)
        #print(f"merge_prints debug: processing print {raw_print.get('expansion') or raw_print.get('deck_kit') or ''!r}")
        name = raw_print.get("expansion") or raw_print.get("deck_kit") or ""
        matches = unused.get(normalize(name))
        #print(unused)
        if matches:
            entry = matches.pop(0)
            print(entry)
            merged["image_url"] = image_url(entry.get("image"))
            merged["illustrator"] = entry.get("illustrator")
            #print(f"merge_prints debug: matched {name!r} -> {entry.get('set')!r}, image={image_url(entry.get('image'))}")
        else:
            #print(f"merge_prints debug: no gallery match for {name!r}")
            pass
        #merged["expansion"] = merged.get("expansion" and expa)
        prints.append(merged)

    for leftovers in unused.values():
        print(f"current prints {prints}")
        for entry in leftovers:
            print(f"an entry {entry}")
            input("Press Enter to continue...")  # Pause for debugging
            prints.append({
                #"expansion_id": entry.get("set") and expansions.link(entry.get("set")),
                "image_url": image_url(entry.get("image")),
                "illustrator": entry.get("illustrator"),
            })
    return prints


def rules_text(card_text):
    """Attack, ability and trainer text as one searchable string."""
    lines = []
    for entry in card_text:
        pieces = [entry.get("name"), entry.get("effect"), entry.get("text")]
        line = ": ".join(piece for piece in pieces if piece)
        if line and line not in lines:
            lines.append(line)
    return "\n".join(lines)


def pokemon_names(raw):
    """Pokémon a card shows: the pokedex names, else the infobox species."""
    names = [entry.get("name") for entry in raw.get("pokedex", [])]
    if not any(names):
        names = [raw.get("infobox", {}).get("species")]
    return unique_names(names)


# ---------- entity records ----------
def merge_dex_entries(entries):
    """Games that share identical entry text (and form) become one entry with a list of games."""
    merged = {}
    for entry in entries:
        key = (entry.get("entry"), entry.get("form"))
        if key not in merged:
            item = {"entry": entry.get("entry"), "games": []}
            if entry.get("form"):
                item["form"] = entry["form"]
            merged[key] = item
        game = entry.get("game")
        if game and game not in merged[key]["games"]:
            merged[key]["games"].append(game)
    return list(merged.values())


class Collection:
    """The records of one kind (pokemon, artist, expansion), keyed by id."""

    def __init__(self, kind, ids):
        self.kind = kind
        self.ids = ids
        self.records = {}
        self.stubs = []

    def add(self, name, **fields):
        record_id = self.ids.make(self.kind, name)
        if record_id not in self.records:
            self.records[record_id] = {"id": record_id, "name": name, **fields,
                                       "has_page": True, "cards": []}
        return record_id

    def link(self, name):
        """The id for a name a card uses, creating a stub record if there is none."""
        record_id = self.ids.find(self.kind, name)
        if record_id is None:
            record_id = self.add(name)
            self.records[record_id]["has_page"] = False
            self.stubs.append(name)
        return record_id


def ref(collection, name):
    return {"id": collection.link(name), "name": name}


# ---------- main ----------
def build():
    raw_cards = load_first("cards.json")
    raw_pokemon = load_first("pokemon.json")
    raw_artists = load_first("artist.json", "artists.json")
    raw_expansions = load_first("expansions.json")

    ids = Ids()
    pokemon = Collection("pokemon", ids)
    artists = Collection("artist", ids)
    expansions = Collection("expansion", ids)

    for raw in raw_pokemon:
        entries = merge_dex_entries(raw.get("pokedex_entries", []))
        pokemon.add(raw["name"], biology=raw.get("biology", ""), pokedex_entries=entries,
                    pokedex_text="\n".join(e["entry"] for e in entries if e["entry"]))
    for raw in raw_artists:
        artists.add(raw["name"], description=raw.get("description", ""), artwork=raw.get("artwork", ""))
    for raw in raw_expansions:
        expansions.add(raw["name"], size=to_int(raw.get("size")), blurb=raw.get("blurb", ""),
                       information=raw.get("information", ""))

    # tags are the categories that are not "<expansion> cards" or "Illus. by ..."
    expansion_keys = {normalize(r["name"]) for r in raw_expansions}
    names_path = EXTRACTED_DIR / "expansion_names.json"  # written by extract_expansions.py
    if names_path.exists():
        expansion_keys |= {normalize(name) for name in read_json(names_path)}

    def tags_from(categories, prints):
        own_sets = {normalize(n) for p in prints for n in (p.get("expansion"), p.get("deck_kit")) if n}
        tags = []
        for category in categories:
            if category.startswith("Illus. by "):
                continue
            set_key = normalize(category[: -len(" cards")]) if category.endswith(" cards") else None
            if set_key in expansion_keys or set_key in own_sets:
                continue
            tags.append(category[: -len(" cards")] if category.endswith(" cards") else category)
        return tags

    dex_numbers = {}      # normalized pokemon name -> national dex number
    problems = defaultdict(list)
    cards = []
    card_ids = Ids()
    link_methods = Counter()  # how each print's image was tied to it during extraction
    old_format = 0

    for raw in raw_cards:
        info = raw.get("infobox", {})
        kind = card_kind(raw)
        if "gallery" in raw:
            old_format += 1  # extracted before the gallery was merged into the prints
 
        pre_prints = [dict(p) for p in raw.get("prints", [])]
        prints = []
        for print_ in pre_prints:
            new_print = dict()
            set_name = print_.get("expansion") or print_.get("deck_kit")
            new_print["set_id"] = expansions.link(set_name) if set_name else None
            new_print["artist_name"] = print_.get("illustrator")
            new_print["artist_id"] = artists.link(print_["illustrator"]) if new_print["artist_name"] else None
            new_print["image_url"] = image_url(print_["image"]) if print_.get("image") else None
            new_print["card_number"] = print_.get("card_number")
            # any print with null fields does not pass
            if any(new_print.get(field) is None for field in ("set_id", "artist_id", "image_url")):
                problems["print with missing fields"].append(raw["title"])
                continue
            prints.append(new_print)

        artist_names = unique_names(list(raw.get("artists", [])) + [p.get("illustrator") for p in prints])
        pokemon_list = pokemon_names(raw)
        for entry in raw.get("pokedex", []):
            number = to_int(entry.get("ndex"))
            if entry.get("name") and number is not None:
                dex_numbers.setdefault(normalize(entry["name"]), number)

        card = {
            "id": card_ids.make("card", raw["title"]),
            "title": raw["title"],
            "name": info.get("cardname") or raw["title"],
            "kind": kind,
            "subtype": info.get("subclass"),
            "stage": info.get("evostage"),
            "type": info.get("type"),
            "hp": to_int(info.get("hp")),
            "weakness": info.get("weakness"),
            "resistance": info.get("resistance"),
            "retreat_cost": to_int(info.get("retreatcost")),
            "evolves_from": info.get("evoname") or info.get("evospecies"),
            "pokemon": [ref(pokemon, n) for n in pokemon_list],
            "artists": [ref(artists, n) for n in artist_names],
            "expansions": [],  # filled in after prints are processed
            "prints": prints,
            "card_text": raw.get("card_text", []),
            "rules_text": rules_text(raw.get("card_text", [])),
            "release_information": flatten_blocks(raw.get("release_information", [])),
            "trivia": flatten_blocks(raw.get("trivia", [])),
            "tags": tags_from(raw.get("categories", []), prints),
        }
        expansion_ids = unique_names([p["set_id"] for p in prints if p.get("set_id")])
        card["expansions"] = [{"id": i, "name": expansions.records[i]["name"]} for i in expansion_ids]

        for field, number in (("hp", info.get("hp")), ("retreatcost", info.get("retreatcost"))):
            if number and to_int(number) is None:
                problems["non-numeric " + field].append(raw["title"])
        if kind == "pokemon" and not pokemon_list:
            problems["pokemon card with no pokemon"].append(raw["title"])
        if not artist_names:
            problems["card with no artist"].append(raw["title"]) # harmless, all are energies
        if not prints:
            problems["card with no english print"].append(raw["title"])
            continue # dont include cards with no english print
        for print_ in prints:
            link_methods[print_.get("link") or ("image not linked to a print" if print_.get("image_url") else "no image")] += 1
            if print_.get("image_url") and not print_.get("artist_id"):
                problems["print with an image but no illustrator"].append(raw["title"])
                card = None
                break
        if not card:
            continue

        cards.append(card)
    # reverse the card links onto the entities
    for card in cards:
        for field, collection in (("pokemon", pokemon), ("artists", artists), ("expansions", expansions)):
            for linked in card[field]:
                record = collection.records[linked["id"]]
                if card["id"] not in record["cards"]:
                    record["cards"].append(card["id"])
    for name, number in dex_numbers.items():
        record_id = ids.find("pokemon", name)
        if record_id:
            pokemon.records[record_id]["national_dex"] = number
    for collection in (pokemon, artists, expansions):
        for record in collection.records.values():
            record["card_count"] = len(record["cards"])

    # write
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        (OUT_DIR / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    write("cards.json", cards)
    write("pokemon.json", list(pokemon.records.values()))
    write("artists.json", list(artists.records.values()))
    write("expansions.json", list(expansions.records.values()))

    report = {
        "counts": {
            "cards": len(cards), "pokemon": len(pokemon.records),
            "artists": len(artists.records), "expansions": len(expansions.records),
        },
        "stub_records_created": {
            "pokemon": pokemon.stubs, "artists": artists.stubs, "expansions": expansions.stubs,
        },
        "records_with_no_cards": {
            "pokemon": [r["name"] for r in pokemon.records.values() if not r["cards"]],
            "artists": [r["name"] for r in artists.records.values() if not r["cards"]],
            "expansions": len([r for r in expansions.records.values() if not r["cards"]]),
        },
        "id_collisions": ids.collisions + card_ids.collisions,
        "problems": {kind: titles for kind, titles in problems.items()},
    }
    write("links_report.json", report)

    print(f"{len(cards)} cards, {len(pokemon.records)} pokemon, "
          f"{len(artists.records)} artists, {len(expansions.records)} expansions -> {OUT_DIR}")
    print(f"stub records (referenced by cards, no page): {len(pokemon.stubs)} pokemon, "
          f"{len(artists.stubs)} artists, {len(expansions.stubs)} expansions")
    print(f"id collisions: {len(report['id_collisions'])}")
    for kind, titles in problems.items():
        print(f"{kind}: {len(titles)}  e.g. {titles[:3]}")


if __name__ == "__main__":
    build()