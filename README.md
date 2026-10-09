Run the full Bulbapedia data pipeline from the repository root:

```powershell
uv run main.py
```

The pipeline fetches card and expansion pages, processes `cards.json`, builds
indexes of the artists and Pokémon referenced by those cards, fetches those
entity pages, then writes `artist.json`, `pokemon.json`, and `expansions.json`.
Fetched wikitext is saved under `data/`.

Pipeline stages can also be run individually:

- `fetching/fetch_cards.py`
- `extracting/extract_cards.py`
- `fetching/fetch_entities.py`
- `extracting/extract_entities.py`
- `extracting/extract_expansions.py`
- `quality_check.py`

Run the quality statistics independently with `uv run quality_check.py`.