"""Turn saved expansion pages into data/expansions.json."""
import json
from pathlib import Path

import mwparserfromhell

from extracting.wikitextUtils import card_files, render, sections, template_name, title_of


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
            if template_name(template) == "tcgexpansioninfobox"
        ),
        None,
    )
    if infobox is None:
        return None

    name = render(infobox.get("setname").value) if infobox.has("setname") else ""
    size_param = next(
        (param for param in ("encards", "jacards") if infobox.has(param)),
        None,
    )
    size = render(infobox.get(size_param).value) if size_param else ""
    if not name:
        name = title_of(path).removesuffix(" (TCG)")

    return {
        "size": size,
        "name": name,
        "blurb": _section_text(wikitext, "blurb"),
        "information": _section_text(wikitext, "information"),
    }


def build_json(data_dir="data"):
    """Build the expansion JSON from TCG pages in each data subdirectory."""
    data_dir = Path(data_dir)
    expansions = []
    directories_with_cards = (
        {path.parent for path in card_files(data_dir)}
        if ONLY_EXPANSIONS_WITH_CARDS
        else None
    )

    for path in sorted(data_dir.glob("*/*_(TCG).wikitext")):
        if directories_with_cards is not None and path.parent not in directories_with_cards:
            continue
        wikitext = path.read_text(encoding="utf-8")
        expansion = _expansion_fields(wikitext, path)
        if expansion is not None:
            expansions.append(expansion)

    out_path = data_dir / "expansions.json"
    out_path.write_text(
        json.dumps(expansions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(expansions)} expansions -> {out_path}")
    return expansions


if __name__ == "__main__":
    build_json()
