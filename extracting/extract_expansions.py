"""Turn saved expansion pages into data/expansions.json."""
import json
import re
from pathlib import Path

import mwparserfromhell

from extracting.wikitextUtils import render, sections, template_name, title_of


ONLY_EXPANSIONS_WITH_CARDS = True


def _section_text(wikitext, section_name):
    """Return the rendered text of a top-level section and its subsections."""
    text = []
    inside = False
    for level, heading, body in sections(wikitext):
        if inside and level <= 2:
            break
        if level == 2:
            inside = (heading or "").casefold() == section_name
        if inside:
            rendered = render(body)
            if rendered:
                text.append(rendered)
    return "\n\n".join(text)


def _expansion_fields(wikitext, path):
    code = mwparserfromhell.parse(wikitext)
    infobox = next(
        (
            template for template in code.filter_templates(recursive=False)
            if template_name(template) in {"tcgexpansioninfobox", "tcgpromoinfobox"}
        ),
        None,
    )
    if infobox is None:
        return []

    if infobox.has("setname"):
        raw_names = re.sub(r"<br\s*/?>", "|", str(infobox.get("setname").value), flags=re.I)
        names = [render(name) for name in raw_names.split("|")]
        names = [name for name in names if name]
    else:
        names = [title_of(path).removesuffix(" (TCG)")]

    size_param = next(
        (param for param in ("encards", "jacards", "cards") if infobox.has(param)),
        None,
    )
    if size_param:
        raw_sizes = re.sub(r"<br\s*/?>", "|", str(infobox.get(size_param).value), flags=re.I)
        sizes = [render(size) for size in raw_sizes.split("|")]
        if len(sizes) != len(names):
            sizes = [render(infobox.get(size_param).value)] * len(names)
    else:
        sizes = [""] * len(names)

    return [
        {
            "size": size,
            "name": name,
            "blurb": _section_text(wikitext, "blurb"),
            "information": _section_text(wikitext, "information"),
        }
        for name, size in zip(names, sizes)
    ]


def _normalized(value):
    return " ".join(value.split()).casefold()


def build_json(data_dir="data"):
    """Build the expansion JSON from TCG pages in each data subdirectory."""
    data_dir = Path(data_dir)
    expansions = []
    card_print_names = set()
    if ONLY_EXPANSIONS_WITH_CARDS:
        cards_path = data_dir / "cards.json"
        with cards_path.open(encoding="utf-8") as file:
            cards = json.load(file)
        card_print_names = {
            _normalized(print_info["expansion"])
            for card in cards
            for print_info in card.get("prints", [])
            if print_info.get("expansion")
        }

    all_names = set()  # every expansion name, including ones with no English cards
    for path in sorted(data_dir.glob("*/*_(TCG).wikitext")):
        wikitext = path.read_text(encoding="utf-8")
        for expansion in _expansion_fields(wikitext, path):
            all_names.add(expansion["name"])
            if ONLY_EXPANSIONS_WITH_CARDS and _normalized(expansion["name"]) not in card_print_names:
                continue
            expansions.append(expansion)

    unique_expansions = {}
    for expansion in expansions:
        key = _normalized(expansion["name"])
        existing = unique_expansions.get(key)
        if existing is None or (
            len(expansion["blurb"]) + len(expansion["information"])
            > len(existing["blurb"]) + len(existing["information"])
        ):
            unique_expansions[key] = expansion
    expansions = list(unique_expansions.values())

    out_path = data_dir / "expansions.json"
    out_path.write_text(
        json.dumps(expansions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(expansions)} expansions -> {out_path}")

    # The full list of names lets build_search_data.py tell "<set> cards" categories apart from
    # real tags like "Holographic cards", even for sets that are filtered out above.
    names_path = data_dir / "expansion_names.json"
    names_path.write_text(
        json.dumps(sorted(all_names, key=str.casefold), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(all_names)} expansion names -> {names_path}")
    return expansions


if __name__ == "__main__":
    build_json()