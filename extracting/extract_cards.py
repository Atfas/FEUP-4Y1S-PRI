"""Turn the saved card wikitext into data/cards.json: one object per card.

Run order:  fetching/fetch_cards.py  ->  extracting/extract_cards.py
Requires:   mwparserfromhell and extracting/wikitextUtils.py

Each card looks like:

    {
      "title": "Abra (151 63)",
      "set": "151",
      "infobox":  {"cardname": "Abra", "hp": "50", ...},
      "artists":  ["Mitsuhiro Arita", "Kouki Saitou"],
      "prints":   [{"expansion": "151", "rarity": "Common", "card_number": "063/165"}, ...],
                  (English products without an expansion, like trainer kits, use "deck_kit"/"half_deck")
      "card_text": [{"kind": "attack", "cost": ["Psychic"], "name": "Psyshot", "damage": "20", ...}],
      "pokedex":  [{"species": "Psi", "ndex": "0063", "dex": "Abra can teleport ...", ...}],
      "gallery":  [{"image": "Abra63PokémonCard151.jpg", "set": "151", "illustrator": "..."}],
      "release_information": [{"heading": null, "text": "..."}],
      "trivia":   [{"heading": null, "text": "..."}, {"heading": "Origin", "text": "..."}],
      "categories": ["151 cards", "Holographic cards", ...]
    }

Japanese-only data (fields starting with "j", Japanese expansions) is left out.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

import mwparserfromhell

from extracting.wikitextUtils import (UNKNOWN_TEMPLATES, card_files, categories, render, sections,
                                      template_name, title_of)

# Infobox fields to keep. Set to None to keep every English field.
INFOBOX_FIELDS = [
    "cardname",
    "species",
    "evostage",
    "evoicon",
    "evospecies",
    "evoname",
    "type",
    "hp",
    "weakness",
    "resistance",
    "retreatcost",
    "class",      # trainer cards: Trainer / Energy
    "subclass",   # trainer cards: Item, Supporter, Stadium, ...
]


PROGRESS_EVERY = 250  # print a progress line every this many cards


# ---------- small helpers ----------
def set_of(path):
    """The set name, decoded from the folder the card was saved in."""
    return unquote(path.parent.name).replace("_", " ")


def find_infobox(templates):
    """The card infobox: the first template named '...Infobox' (not '.../Expansion' or '.../Footer')."""
    for template in templates:
        name = template_name(template)
        if "infobox" in name and "/" not in name:
            return template
    return None


def read_params(template, only=None):
    """A template's parameters as {name: plain text}.

    Skips empty values and Japanese fields (names starting with "j", like jname or jtrans).
    If `only` is given, keeps just those field names.
    """
    params = {}
    for param in template.params:
        name = str(param.name).strip().lower()
        if name.startswith("j"):
            continue
        if only is not None and name not in only:
            continue
        value = render(param.value)
        if value:
            params[name] = value
    return params


def read_energy_cost(template):
    """The attack cost as a list of energy types, e.g. ["Psychic", "Colorless"]."""
    cost = mwparserfromhell.parse(str(template.get("cost").value))
    energies = []
    for energy in cost.filter_templates():
        if template_name(energy) == "e" and energy.has(1):
            energies.append(render(energy.get(1).value))
    return energies


# ---------- one reader per part of the card ----------
def read_infobox(infobox):
    if infobox is None:
        return {}
    return read_params(infobox, only=INFOBOX_FIELDS)


# Print fields we rename; any other English field is copied across unchanged.
PRINT_RENAMES = {"cardno": "card_number", "deckkit": "deck_kit", "halfdeck": "half_deck"}
PRINT_META_FIELDS = {"type", "class"}  # describe the card, not the print


def read_prints(all_templates):
    """One entry per English print, from the .../Expansion templates.

    Trainer pages nest these inside ReleaseInfo templates, so this must be given every
    template on the page, not just the top-level ones. An entry can be an expansion
    ({"expansion", "rarity", "card_number"}) or an English product such as a trainer kit
    ({"deck_kit", "half_deck", "card_number"}). Japanese-only prints end up empty and are skipped.
    """
    prints = []
    for template in all_templates:
        if not template_name(template).endswith("infobox/expansion"):
            continue
        entry = {}
        for name, value in read_params(template).items():
            if name not in PRINT_META_FIELDS:
                entry[PRINT_RENAMES.get(name, name)] = value
        if entry:
            prints.append(entry)
    return prints


def read_card_text(templates):
    """Attacks, abilities and so on (Cardtext/...), and trainer text (TCGTrainerText)."""
    entries = []
    for template in templates:
        name = template_name(template)
        if name == "tcgtrainertext":
            kind = "trainer"
        elif name.startswith("cardtext/") and name not in ("cardtext/header", "cardtext/footer"):
            kind = name.split("/", 1)[1]
        else:
            continue
        entry = {"kind": kind}
        entry.update(read_params(template))
        if template.has("cost"):
            entry["cost"] = read_energy_cost(template)  # replaces the flattened text version
        entries.append(entry)
    return entries


def read_pokedex(templates):
    return [read_params(t) for t in templates if template_name(t) == "carddex"]


def read_gallery(templates):
    """Artwork list from the TCGGallery template (|image1=, |set1=, |illus1=, |image2=, ...)."""
    by_number = {}
    for template in templates:
        if template_name(template) != "tcggallery":
            continue
        for param in template.params:
            match = re.match(r"^(image|set|illus)(\d+)$", str(param.name).strip().lower())
            if match:
                field, number = match.group(1), int(match.group(2))
                by_number.setdefault(number, {})[field] = render(param.value)

    gallery = []
    for number in sorted(by_number):
        entry = by_number[number]
        gallery.append({
            "image": entry.get("image"),
            "set": entry.get("set"),
            "illustrator": entry.get("illus"),
        })
    return gallery


def read_artists(category_names, gallery):
    """Artist names. The 'Illus. by X' categories are the main source; the gallery fills any gaps."""
    names = []
    for category in category_names:
        match = re.match(r"^Illus\. by (.+)$", category)
        if match:
            names.append(match.group(1))
    for entry in gallery:
        illustrator = entry["illustrator"]
        if illustrator and illustrator not in names:
            names.append(illustrator)
    return names


def read_blocks(wikitext, section_name):
    """Text of a top-level section as a list of {"heading", "text"} blocks.

    The section's own text has heading None; each subsection (===Origin===) is its own block.
    The Gallery subsection is skipped, because the gallery is read separately.
    """
    blocks = []
    inside = False
    for level, heading, body in sections(wikitext):
        if level == 0:
            continue
        if level == 2:
            inside = heading.lower() == section_name
        if not inside:
            continue
        if level > 2 and heading.lower() == "gallery":
            continue
        text = render(body)
        if text:
            blocks.append({"heading": heading if level > 2 else None, "text": text})
    return blocks


# ---------- putting a card together ----------
def process_card(path):
    wikitext = path.read_text(encoding="utf-8")
    code = mwparserfromhell.parse(wikitext)
    templates = code.filter_templates(recursive=False)  # top level only
    all_templates = code.filter_templates()             # includes templates nested inside others
    infobox = find_infobox(templates)

    category_names = categories(wikitext)
    gallery = read_gallery(templates)

    card = {
        "title": title_of(path),
        "set": set_of(path),
        "infobox": read_infobox(infobox),
        "artists": read_artists(category_names, gallery),
        "prints": read_prints(all_templates),
        "card_text": read_card_text(templates),
        "pokedex": read_pokedex(templates),
        "gallery": gallery,
        "release_information": read_blocks(wikitext, "release information"),
        "trivia": read_blocks(wikitext, "trivia"),
        "categories": category_names,
    }
    return card, infobox is not None


def build_json(data_dir="data"):
    out_path = Path(data_dir) / "cards.json"

    cards = []
    seen = set()
    no_infobox = []
    no_artist = []

    paths = list(card_files(data_dir))
    total = len(paths)
    started = time.time()
    print(f"processing {total} card pages...", flush=True)

    for number, path in enumerate(paths, 1):
        if number % PROGRESS_EVERY == 0 or number == total:
            elapsed = time.time() - started
            remaining = elapsed / number * (total - number)
            print(f"  {number}/{total} ({number / total:.0%})  "
                  f"{elapsed:.0f}s elapsed, ~{remaining:.0f}s left", flush=True)

        title = title_of(path)
        if title in seen:  # the same page can be saved under more than one set folder
            continue
        seen.add(title)

        card, had_infobox = process_card(path)
        if not had_infobox:
            no_infobox.append(title)
        if not card["artists"]:
            no_artist.append(title)
        cards.append(card)

    print("writing json...", flush=True)
    out_path.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(cards)} cards -> {out_path}")
    print(f"{len(no_infobox)} with no infobox: {no_infobox[:5]}")
    print(f"{len(no_artist)} with no artist: {no_artist[:5]}")
    print("templates render() did not recognise (most common first):")
    for name, count in UNKNOWN_TEMPLATES.most_common(15):
        print(f"  {name:<30} {count}")
    return cards


if __name__ == "__main__":
    build_json()