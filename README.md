# Bulbapedia

This project builds a structured Pokémon TCG dataset from Bulbapedia pages by fetching wikitext, turning it into JSON records, enriching entity data for artists and Pokémon, and combining that with market-price data from TCGplayer before running a quality pipeline over the final output.

## Data sources

- Bulbapedia provides the main card, expansion, artist, and Pokémon records extracted from wikitext pages.
- TCGplayer adds market-price data that enriches the final card dataset with pricing context.

## Requirements

- Python 3.14+
- `uv` (recommended for dependency and script management)

Install dependencies:

```powershell
uv sync
```

## Run the full pipeline

From the repository root:

```powershell
uv run main.py
```

`main.py` runs the complete data workflow in order:

1. Fetch raw expansion and card wikitext into `data/`
2. Extract card records into `data/cards.json`
3. Build indexes of Pokémon and artist names referenced by those cards
4. Fetch the referenced Pokémon and artist pages
5. Fetch price data for the expansions from TCGplayer into `data/price_data/` and related JSON outputs
6. Extract enriched entity and expansion records
7. Clean and normalize processed card data
8. Merge price data into the processed records
9. Generate the quality report at `quality_report.md`

## Pipeline stages

The pipeline can also be run step by step:

- `fetching/fetch_cards.py`
- `extracting/extract_cards.py`
- `fetching/fetch_entities.py`
- `fetching/fetch_prices.py`
- `extracting/extract_entities.py`
- `extracting/extract_expansions.py`
- `extracting/extract_prices.py`
- `processing/process_cards.py`
- `processing/merge_prices.py`
- `quality_check.py`

## Outputs

The full pipeline writes structured JSON data under `data/` and a root-level quality report:

- `data/cards.json`
- `data/pokemon.json`
- `data/artists.json`
- `data/expansions.json`
- `data/price_report.json`
- `data/_indexes/pokemon.json`
- `data/_indexes/artists.json`
- `quality_report.md`

The quality report checks dataset completeness, searchable-text lengths, duplicate identifiers, link coverage, missing entity references, representative sample coverage, and any pricing anomalies or missing price records.

To generate the report on its own:

```powershell
uv run quality_check.py
```

## Project structure

- `fetching/` — downloads raw wikitext and related data
- `extracting/` — converts raw pages into structured JSON
- `processing/` — cleans, normalizes, merges, and analyzes processed records
- `search/` — search-ready and derived datasets
- `data/` — pipeline caches and output data
