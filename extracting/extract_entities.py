"""Turn saved artist and Pokémon pages into data/artist.json and data/pokemon.json."""
import json
import re
from pathlib import Path

import mwparserfromhell

from extracting.wikitextUtils import (disambiguation_target, drop_count_sentences,
                                      is_disambiguation, render, sections, template_name,
                                      title_of)


def _normalized_heading(heading):
    return (heading or "").casefold().replace("é", "e")


def _section_text(wikitext, section_name, level):
    """Collect rendered text from a section and all of its subsections."""
    text = []
    inside = False
    for section_level, heading, body in sections(wikitext):
        if inside and section_level <= level:
            break
        if section_level == level and _normalized_heading(heading) == section_name:
            inside = True
        if inside:
            rendered = render(body)
            if rendered:
                text.append(rendered)
    return "\n\n".join(text)


def _lead_text(wikitext):
    for level, _, body in sections(wikitext):
        if level == 0:
            return render(body)
    return ""


def _pokedex_entries(wikitext):
    entries = []
    in_game_data = False

    for level, heading, body in sections(wikitext):
        if level == 2:
            in_game_data = _normalized_heading(heading) == "game data"
        if not (in_game_data and level == 3 and
                _normalized_heading(heading) == "pokedex entries"):
            continue

        form = None
        for template in mwparserfromhell.parse(body).filter_templates():
            name = template_name(template)
            if name == "dex/form":
                form = render(template.get(1).value) if template.has(1) else None
                continue
            if not re.fullmatch(r"dex/entry\d*", name) or not template.has("entry"):
                continue

            text = render(template.get("entry").value)
            if not text:
                continue

            # Dex/Entry2 and Dex/Entry3 name several games: |v=HeartGold|v2=SoulSilver.
            # Keep one entry per game, so none of them is lost.
            games = []
            for param in template.params:
                if re.fullmatch(r"(v|game|version)\d*", str(param.name).strip().lower()):
                    game = render(param.value)
                    if game:
                        games.append(game)

            for game in games or [None]:
                entry = {"entry": text}
                if game:
                    entry["game"] = game
                if form:
                    entry["form"] = form
                entries.append(entry)

    return entries


def _page_lookup(folder, pokemon=False):
    """Map each page name to its saved file, including names that are redirects to a saved page."""
    def display_name(title):
        if pokemon and title.endswith(" (Pokémon)"):
            return title[:-len(" (Pokémon)")]
        return title

    pages = {}
    for path in sorted(folder.glob("*.wikitext")):
        pages.setdefault(display_name(title_of(path)), path)

    # The fetch step saves a redirected page under its final title and records
    # {requested title: final title} in _redirects.json, e.g. "Mr Mime (Pokémon)" -> "Mr. Mime (Pokémon)".
    redirects_file = folder / "_redirects.json"
    if redirects_file.exists():
        redirects = json.loads(redirects_file.read_text(encoding="utf-8"))
        for requested, final in redirects.items():
            if display_name(final) in pages:
                pages.setdefault(display_name(requested), pages[display_name(final)])
    return pages


def _indexed_names(index_path):
    with index_path.open(encoding="utf-8") as file:
        return json.load(file).keys()


def _process_artists(data_dir):
    pages = _page_lookup(data_dir / "artists")
    artists = []
    missing = []
    resolved = []     # ambiguous names whose illustrator page was found
    unresolved = []   # ambiguous names where it was not
    for name in sorted(_indexed_names(data_dir / "_indexes" / "artists.json"), key=str.casefold):
        path = pages.get(name)
        if path is None:
            missing.append(name)
            continue
        wikitext = path.read_text(encoding="utf-8")

        # An ambiguous name (e.g. "Akagi") lands on a disambiguation page. The artist's own page
        # is the one it links to for the TCG illustrator, e.g. "Akagi (illustrator)".
        if is_disambiguation(wikitext):
            target = disambiguation_target(wikitext)
            target_path = pages.get(target) if target else None
            if target_path is None:
                unresolved.append(name)
                artists.append({"name": name, "description": "", "artwork": ""})
                continue
            resolved.append(name)
            wikitext = target_path.read_text(encoding="utf-8")

        # Drop sentences that only report live card counts; rendered, they would leave gaps.
        wikitext = drop_count_sentences(wikitext)
        artists.append({

            "name": name,
            "description": _lead_text(wikitext),
            "artwork": _section_text(wikitext, "artwork", 2),
        })

    out_path = data_dir / "artist.json"
    out_path.write_text(json.dumps(artists, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(artists)} artists -> {out_path}")
    if missing:
        print(f"{len(missing)} indexed artists have no saved page")
    if resolved or unresolved:
        print(f"{len(resolved)} disambiguation pages resolved, {len(unresolved)} unresolved: {unresolved[:5]}")
    return artists


def _process_pokemon(data_dir):
    pages = _page_lookup(data_dir / "pokemon", pokemon=True)
    pokemon = []
    missing = []
    for name in sorted(_indexed_names(data_dir / "_indexes" / "pokemon.json"), key=str.casefold):
        path = pages.get(name)
        if path is None:
            missing.append(name)
            continue
        wikitext = path.read_text(encoding="utf-8")
        pokemon.append({
            "name": name,
            "pokedex_entries": _pokedex_entries(wikitext),
            "biology": _section_text(wikitext, "biology", 2),
        })

    out_path = data_dir / "pokemon.json"
    out_path.write_text(json.dumps(pokemon, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(pokemon)} Pokémon -> {out_path}")
    if missing:
        print(f"{len(missing)} indexed Pokémon have no saved page")
    return pokemon


def build_json(data_dir="data"):
    """Build the two entity indexes from the saved Bulbapedia pages."""
    data_dir = Path(data_dir)
    _process_artists(data_dir)
    _process_pokemon(data_dir)


if __name__ == "__main__":
    build_json()