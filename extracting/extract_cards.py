"""Turn the saved card wikitext into data/cards.json: one object per card.

Run order:  fetching/fetch_cards.py  ->  extracting/extract_cards.py
Requires:   mwparserfromhell and extracting/wikitextUtils.py

Each card looks like:

    {
      "title": "Abra (151 63)",
      "set": "151",
      "infobox":  {"cardname": "Abra", "hp": "50", ...},
      "artists":  ["Mitsuhiro Arita", "Kouki Saitou"],
      "prints":   [{"expansion": "151", "rarity": "Common", "card_number": "063/165",
                    "image": "Abra63PokémonCard151.jpg", "illustrator": "Mitsuhiro Arita", "link": "set"}, ...],
                  (English products without an expansion, like trainer kits, use "deck_kit"/"half_deck";
                   "link" says how the picture was tied to the print: set, caption, number, order, only;
                   a picture that matches no print is kept as an entry with "link": null)
      "card_text": [{"kind": "attack", "cost": ["Psychic"], "name": "Psyshot", "damage": "20", ...}],
      "pokedex":  [{"species": "Psi", "ndex": "0063", "dex": "Abra can teleport ...", ...}],
      "release_information": [{"heading": null, "text": "..."}],
      "trivia":   [{"heading": null, "text": "..."}, {"heading": "Origin", "text": "..."}],
      "categories": ["151 cards", "Holographic cards", ...]
    }

Japanese-only data (fields starting with "j", Japanese expansions) is left out.
"""
import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import mwparserfromhell

from extracting.wikitextUtils import (UNKNOWN_TEMPLATES, card_files, categories, read_blocks,
                                      render, template_name, title_of)

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


def norm_name(text):
    """Lower case, no accents, single spaces: 'Pokémon  Card 151' and 'pokemon card 151' compare equal."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\W+", " ", text.casefold()).strip()


def read_caption(caption):
    """Split a picture caption into (label, illustrator).

    '{{TCG|Special illustration rare}} print<br>Illus. [[Shinya Komatsu]]'
        -> ("Special illustration rare", "Shinya Komatsu")
    'Regular print<br>Illus. [[Mitsuhiro Arita]]' -> ("Regular", "Mitsuhiro Arita")

    The label says which print the picture shows: a set ('{{TCG|Paldean Fates}} print'), a kind of
    print ('Special illustration rare'), or just 'Regular'.
    """
    text = str(caption)
    parts = re.split(r"<br\s*/?>", text, maxsplit=1, flags=re.I)
    head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
    if not tail:  # no line break: split at "Illus." instead
        pieces = re.split(r"illus\.", text, maxsplit=1, flags=re.I)
        if len(pieces) == 2:
            head, tail = pieces

    label = re.sub(r"\s*print\s*$", "", render(head), flags=re.I).strip() or None

    after = re.split(r"illus\.", tail, maxsplit=1, flags=re.I)[-1]
    link = re.search(r"\[\[([^\]|]+)", after)  # [[Page]] or [[Page|text]]: the page is the artist's name
    illustrator = link.group(1).strip() if link else (render(after) or None)
    return label, illustrator


def read_gallery(templates):
    """Pictures from the TCGGallery template: image, and the set and illustrator when they are given.

    Two layouts exist:  |image1=..|set1=151|illus1=Name   and   |image1=..|caption1=Regular print<br>Illus. [[Name]]
    """
    by_number = {}
    for template in templates:
        if template_name(template) != "tcggallery":
            continue
        for param in template.params:
            match = re.match(r"^(image|set|illus|caption)(\d+)$", str(param.name).strip().lower())
            if match:
                by_number.setdefault(int(match.group(2)), {})[match.group(1)] = param.value

    pictures = []
    for number in sorted(by_number):
        entry = by_number[number]
        image = render(entry["image"]) if "image" in entry else ""
        if not image:
            continue
        label, caption_illustrator = read_caption(entry["caption"]) if "caption" in entry else (None, None)
        pictures.append({
            "image": image,
            "set": render(entry["set"]) or None if "set" in entry else None,
            "label": label,
            "illustrator": (render(entry["illus"]) if "illus" in entry else None) or caption_illustrator,
        })
    return pictures


def read_infobox_pictures(infobox):
    """Pictures from the infobox (|image=, |caption=, |reprint1=, |recaption1=, ...).

    Used only for pages that have no gallery, so a card with a single print still gets its image.
    """
    if infobox is None:
        return []
    params = {str(p.name).strip().lower(): p.value for p in infobox.params}
    slots = [("image", "caption")] if "image" in params else []
    numbers = sorted(int(m.group(1)) for key in params if (m := re.fullmatch(r"reprint(\d+)", key)))
    slots += [(f"reprint{n}", f"recaption{n}") for n in numbers]

    pictures = []
    for image_key, caption_key in slots:
        image = render(params[image_key])
        if not image:
            continue
        label, illustrator = read_caption(params[caption_key]) if caption_key in params else (None, None)
        pictures.append({"image": image, "set": None, "label": label, "illustrator": illustrator})
    return pictures


# ---------- linking pictures to prints ----------
def print_set(print_):
    return print_.get("expansion") or print_.get("deck_kit") or ""


def print_number(print_):
    """The first number in the card number: '063/165' -> 63, 'SWSH039' -> 39."""
    match = re.search(r"\d+", print_.get("card_number") or "")
    return int(match.group()) if match else None


def find_print(picture, prints, free, may_pair_by_order):
    """Which of the free prints does this picture show? -> (index, how) or (None, None).

    Evidence, strongest first:
      set      the gallery names the set (|set1=151)
      caption  the caption names a set, or a kind of print that is a print's rarity
      number   a number in the image file name is the print's card number (Alakazamex201...jpg -> 201)
      order    pictures and prints are equally many and nothing else decided: take the next one
    """
    candidates = list(free)
    evidence = []

    if picture["set"]:
        narrowed = [i for i in candidates if norm_name(print_set(prints[i])) == norm_name(picture["set"])]
        if not narrowed:
            return None, None  # the gallery names a set none of the free prints belongs to
        candidates, evidence = narrowed, evidence + ["set"]

    label = norm_name(picture["label"])
    if label and label != "regular" and len(candidates) > 1:
        by_set = [i for i in candidates if norm_name(print_set(prints[i])) == label]
        by_rarity = [i for i in candidates if norm_name(prints[i].get("rarity")) == label]
        narrowed = by_set or by_rarity
        if narrowed:
            candidates, evidence = narrowed, evidence + ["caption"]

    if len(candidates) > 1:
        numbers = {int(n) for n in re.findall(r"\d+", picture["image"])}
        narrowed = [i for i in candidates if print_number(prints[i]) in numbers]
        if narrowed:
            candidates, evidence = narrowed, evidence + ["number"]

    if len(candidates) == 1:
        return candidates[0], "+".join(evidence) or "only"
    if candidates and may_pair_by_order:
        return candidates[0], "order"
    return None, None


def link_pictures(prints, pictures):
    """One list of prints, each with its image and illustrator when a picture could be linked.

    A picture that matches no print is kept as an entry of its own (with "link": None), so nothing
    is lost. Each print gets "link" saying what evidence tied it to its picture.
    """
    linked = [dict(p) for p in prints]
    taken = set()
    unlinked = []
    may_pair_by_order = len(pictures) == len(prints)

    for picture in pictures:
        free = [i for i in range(len(linked)) if i not in taken]
        index, how = find_print(picture, linked, free, may_pair_by_order)
        if index is None:
            entry = {"image": picture["image"], "illustrator": picture["illustrator"], "link": None}
            if picture["set"]:
                entry["expansion"] = picture["set"]
            unlinked.append(entry)
            continue
        taken.add(index)
        linked[index].update(image=picture["image"], illustrator=picture["illustrator"], link=how)
    return linked + unlinked


def read_artists(category_names, prints):
    """Artist names. The 'Illus. by X' categories are the main source; the prints' illustrators fill any gaps."""
    names = []
    for category in category_names:
        match = re.match(r"^Illus\. by (.+)$", category)
        if match:
            names.append(match.group(1))
    for print_ in prints:
        illustrator = print_.get("illustrator")
        if illustrator and illustrator not in names:
            names.append(illustrator)
    return names


# ---------- putting a card together ----------
def process_card(path):
    wikitext = path.read_text(encoding="utf-8")
    code = mwparserfromhell.parse(wikitext)
    templates = code.filter_templates(recursive=False)  # top level only
    all_templates = code.filter_templates()             # includes templates nested inside others
    infobox = find_infobox(templates)

    category_names = categories(wikitext)
    # Prints (rarity, card number) and pictures (image, illustrator) come from different places on
    # the page; link_pictures joins them into one list.
    pictures = read_gallery(templates) or read_infobox_pictures(infobox)
    prints = link_pictures(read_prints(all_templates), pictures)

    card = {
        "title": title_of(path),
        "set": set_of(path),
        "infobox": read_infobox(infobox),
        "artists": read_artists(category_names, prints),
        "prints": prints,
        "card_text": read_card_text(templates),
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
    links = Counter()  # how each print's picture was linked

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
        for print_ in card["prints"]:
            links[print_.get("link") or ("image not linked to a print" if print_.get("image") else "no image")] += 1
        cards.append(card)

    print("writing json...", flush=True)
    out_path.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(cards)} cards -> {out_path}")
    print(f"{len(no_infobox)} with no infobox: {no_infobox[:5]}")
    print(f"{len(no_artist)} with no artist: {no_artist[:5]}")
    print("prints by how their image was linked:", dict(links.most_common()))
    print("templates render() did not recognise (most common first):")
    for name, count in UNKNOWN_TEMPLATES.most_common(15):
        print(f"  {name:<30} {count}")
    return cards


if __name__ == "__main__":
    build_json()