"""Run the complete Bulbapedia data pipeline."""
from fetching.fetch_cards import build_dataset
from fetching.fetch_entities import (
    build_indexes,
    fetch_artists,
    fetch_pokemon,
)
from extracting.extract_cards import build_json as process_cards
from extracting.extract_entities import build_json as process_entities
from extracting.extract_expansions import build_json as process_expansions
from quality_check import check_data_quality


def run_pipeline(data_dir="data", max_expansions=None):
    """Fetch and process cards, related entities, and expansions in dependency order."""
    build_dataset(out_dir=data_dir, max_expansions=max_expansions)
    process_cards(data_dir=data_dir)

    pokemon, artists = build_indexes(data_dir=data_dir)
    fetch_pokemon(pokemon, data_dir=data_dir)
    fetch_artists(artists, data_dir=data_dir)

    process_entities(data_dir=data_dir)
    process_expansions(data_dir=data_dir)
    check_data_quality(data_dir=data_dir)


if __name__ == "__main__":
    run_pipeline()
