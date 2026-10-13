"""Run the complete Bulbapedia data pipeline."""
from fetching.fetch_cards import build_dataset
from fetching.fetch_entities import (
    build_indexes,
    fetch_artists,
    fetch_pokemon,
)
from fetching.fetch_prices import fetch_all as fetch_prices

from extracting.extract_cards import build_json as extract_cards
from extracting.extract_entities import build_json as extract_entities
from extracting.extract_expansions import build_json as extract_expansions
from extracting.extract_prices import build_json as extract_prices

from quality_check import build_quality_report
from processing.process_cards import build as process_cards
from processing.merge_prices import merge as merge_prices

def run_pipeline(data_dir="data", max_expansions=None):
    """Fetch and process cards, related entities, and expansions in dependency order."""
    # step 1: fetch the wikitext for all expansions and their cards
    build_dataset(out_dir=data_dir, max_expansions=max_expansions)
    # step 2: extract the card data from the wikitext into json, keeping only wanted fields
    extract_cards(data_dir=data_dir)

    # step 3: extract entity(pokemon and artist) data from the cards json, and fetch their wikitext pages
    pokemon, artists = build_indexes(data_dir=data_dir)
    fetch_pokemon(pokemon, data_dir=data_dir)
    fetch_artists(artists, data_dir=data_dir)
    fetch_prices()  # fetches tcgplayer prices for all expansions
    
    #step 4: extract the entity data from the wikitext into json, keeping only wanted fields
    extract_entities(data_dir=data_dir)
    extract_expansions(data_dir=data_dir)
    extract_prices(data_dir=data_dir)
    
    #step 5: remove unwanted information, cards with nulls, repeated cards,
    process_cards()
    merge_prices()
    
    build_quality_report(data_dir=data_dir)


if __name__ == "__main__":
    run_pipeline()
