"""Print basic completeness and relationship statistics for the generated JSON files."""
import json
from pathlib import Path


def _read_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _count_nulls(value, path="$"):
    if value is None:
        return {path: 1}
    if isinstance(value, dict):
        counts = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path != "$" else key
            for field, count in _count_nulls(item, child_path).items():
                counts[field] = counts.get(field, 0) + count
        return counts
    if isinstance(value, list):
        counts = {}
        child_path = f"{path}[]"
        for item in value:
            for field, count in _count_nulls(item, child_path).items():
                counts[field] = counts.get(field, 0) + count
        return counts
    return {}


def _normalized(value):
    return " ".join(str(value).split()).casefold()


def _pokemon_names(card):
    names = [
        entry["name"]
        for entry in card.get("pokedex", [])
        if entry.get("name")
    ]
    if not names:
        species = card.get("infobox", {}).get("species")
        if species:
            names.append(species)
    return names


def _cards_for_entities(index, card_titles):
    return {
        name: set(titles).intersection(card_titles)
        for name, titles in index.items()
    }


def check_data_quality(data_dir="data"):
    """Print record counts, explicit null counts, and unconnected record counts."""
    data_dir = Path(data_dir)
    cards = _read_json(data_dir / "cards.json")
    artists = _read_json(data_dir / "artist.json")
    pokemon = _read_json(data_dir / "pokemon.json")
    expansions = _read_json(data_dir / "expansions.json")
    artist_index = _read_json(data_dir / "_indexes" / "artists.json")
    pokemon_index = _read_json(data_dir / "_indexes" / "pokemon.json")

    card_titles = {card["title"] for card in cards}
    artist_cards = _cards_for_entities(artist_index, card_titles)
    pokemon_cards = _cards_for_entities(pokemon_index, card_titles)
    expansion_names = {_normalized(expansion["name"]) for expansion in expansions}
    card_expansions = {
        _normalized(print_info.get("expansion", ""))
        for card in cards
        for print_info in card.get("prints", [])
    }

    unconnected_cards = 0
    for card in cards:
        title = card["title"]
        has_artist = any(title in artist_cards.get(name, set()) for name in card.get("artists", []))
        has_pokemon = any(title in pokemon_cards.get(name, set()) for name in _pokemon_names(card))
        has_expansion = any(
            _normalized(print_info.get("expansion", "")) in expansion_names
            for print_info in card.get("prints", [])
        )
        if not (has_artist or has_pokemon or has_expansion):
            unconnected_cards += 1

    unconnected_artists = sum(
        not artist_cards.get(artist.get("name"), set()) for artist in artists
    )
    unconnected_pokemon = sum(
        not pokemon_cards.get(entry.get("name"), set()) for entry in pokemon
    )
    unconnected_expansions = sum(
        _normalized(expansion.get("name", "")) not in card_expansions
        for expansion in expansions
    )

    datasets = [
        ("cards.json", cards, unconnected_cards),
        ("artist.json", artists, unconnected_artists),
        ("pokemon.json", pokemon, unconnected_pokemon),
        ("expansions.json", expansions, unconnected_expansions),
    ]

    print(f"{'JSON file':<18} {'Documents':>10} {'Unconnected':>12}")
    for name, records, unconnected in datasets:
        print(f"{name:<18} {len(records):>10} {unconnected:>12}")
        nulls_by_field = _count_nulls(records)
        if nulls_by_field:
            print("  nulls by field:")
            for field, count in sorted(nulls_by_field.items()):
                print(f"    {field}: {count}")
        else:
            print("  nulls by field: none")
    print(
        "\nUnconnected cards have no matching artist, Pokémon, or expansion index link. "
        "Entity links use _indexes/*.json; expansion links match card print names."
    )


if __name__ == "__main__":
    check_data_quality()
