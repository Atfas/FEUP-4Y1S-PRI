"""Fetch the Pokémon and artist pages for every card in data/cards.json.

Run order:  fetching/fetch_cards.py  ->  extracting/extract_cards.py  ->  fetching/fetch_entities.py

Where the names come from (all from cards.json, no extra downloads):
    Pokémon:  the "name" of each entry in the card's "pokedex" list.
              Cards with no pokedex entry fall back to the infobox "species" field.
    Artists:  the card's "artists" list.

Creates:
    data/_indexes/pokemon.json     {Pokémon name: [card titles]}
    data/_indexes/artists.json     {artist name: [card titles]}
    data/pokemon/<Name> (Pokémon).wikitext
    data/artists/<Artist name>.wikitext
and, inside the pokemon and artists folders, _redirects.json and _missing.json.

The card lists stay in the index files, so nothing is copied: to find the cards
for an artist or Pokémon, look the name up in the matching index.
"""
import json
from collections import defaultdict
from pathlib import Path

from fetching.helper import chunks, wikitext_batch
from fetching.storage import safe_name

BATCH_SIZE = 50
POKEMON_BATCH_SIZE = 25  # Pokémon pages are long, so ask for fewer at a time


# ---------- small file helpers ----------
def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def page_path(folder, title):
    return folder / (safe_name(title) + ".wikitext")


# ---------- names and their cards, from cards.json ----------
def pokemon_names(card):
    """The Pokémon this card shows. Usually one; Tag Team style cards can have two."""
    names = []
    for entry in card["pokedex"]:
        name = entry.get("name")
        if name and name not in names:
            names.append(name)
    if not names:  # no pokedex entry on this card: use the infobox species instead
        species = card["infobox"].get("species")
        if species:
            names.append(species)
    return names


def build_indexes(data_dir="data"):
    """Read cards.json, build {name: [card titles]} for Pokémon and artists, and save both."""
    cards_path = Path(data_dir) / "cards.json"
    if not cards_path.exists():
        raise SystemExit(f"{cards_path} not found. Run extracting/extract_cards.py first.")
    cards = read_json(cards_path, [])

    pokemon = defaultdict(list)
    artists = defaultdict(list)
    no_pokemon = []
    no_artist = []

    for card in cards:
        names = pokemon_names(card)
        if not names:
            no_pokemon.append(card["title"])  # trainers and energy cards are expected here
        for name in names:
            pokemon[name].append(card["title"])

        if not card["artists"]:
            no_artist.append(card["title"])
        for name in card["artists"]:
            artists[name].append(card["title"])

    pokemon = dict(sorted(pokemon.items()))
    artists = dict(sorted(artists.items()))
    write_json(Path(data_dir) / "_indexes" / "pokemon.json", pokemon)
    write_json(Path(data_dir) / "_indexes" / "artists.json", artists)

    print(f"{len(cards)} cards read")
    print(f"{len(pokemon)} Pokémon names, {len(no_pokemon)} cards with none: {no_pokemon[:5]}")
    print(f"{len(artists)} artists, {len(no_artist)} cards with none: {no_artist[:5]}")
    return pokemon, artists


# ---------- the shared fetch-and-save loop ----------
def fetch_titles(titles, folder, batch_size=BATCH_SIZE):
    """Fetch wikitext for a list of page titles and save one file per page.

    Titles that are already saved, known redirects, or known missing pages are
    skipped, so the function can be re-run safely after an interruption.
    """
    folder.mkdir(parents=True, exist_ok=True)
    redirects_file = folder / "_redirects.json"
    missing_file = folder / "_missing.json"
    redirects = read_json(redirects_file, {})
    missing = set(read_json(missing_file, []))

    todo = []
    for title in titles:
        already_saved = page_path(folder, title).exists()
        if already_saved or title in redirects or title in missing:
            continue
        todo.append(title)

    skipped = len(titles) - len(todo)
    print(f"  {len(titles)} titles, {skipped} already handled, {len(todo)} to fetch")

    batches = list(chunks(todo, batch_size))
    for number, batch in enumerate(batches, 1):
        pages, moved, gone = wikitext_batch(batch)

        for title, wikitext in pages.items():
            page_path(folder, title).write_text(wikitext, encoding="utf-8")

        # Written after every batch, so an interruption loses at most one batch.
        redirects.update(moved)
        missing.update(gone)
        write_json(redirects_file, redirects)
        write_json(missing_file, sorted(missing))

        print(f"  batch {number}/{len(batches)}: asked {len(batch)}, saved {len(pages)}, "
              f"{len(moved)} redirected, {len(gone)} missing")


def summarize(folder):
    saved = len(list(folder.glob("*.wikitext")))
    redirects = read_json(folder / "_redirects.json", {})
    missing = read_json(folder / "_missing.json", [])
    print(f"  {saved} pages saved, {len(redirects)} redirects, {len(missing)} missing")
    if missing:
        print(f"  first missing: {missing[:10]}")


# ---------- the two entity types ----------
def fetch_pokemon(pokemon, data_dir="data"):
    folder = Path(data_dir) / "pokemon"
    print(f"pokemon: {len(pokemon)} names")

    # Pokémon page titles look like "Abra (Pokémon)".
    titles = [f"{name} (Pokémon)" for name in pokemon]
    fetch_titles(titles, folder, POKEMON_BATCH_SIZE)
    summarize(folder)


def fetch_artists(artists, data_dir="data"):
    folder = Path(data_dir) / "artists"
    print(f"artists: {len(artists)} names")

    # Artist page titles are just the artist's name.
    fetch_titles(list(artists), folder)
    summarize(folder)


if __name__ == "__main__":
    pokemon_index, artist_index = build_indexes()
    fetch_pokemon(pokemon_index)
    fetch_artists(artist_index)