# Pokémon TCG Information Retrieval Project

This project was developed for the **Information Processing and Retrieval
(PRI)** course at FEUP. It collects and prepares Pokémon Trading Card Game
data for a future information-retrieval system.

The current implementation contains extraction and normalization pipelines for
three public sources:

- **TCG API**: Pokémon card and set metadata.
- **Trainer Hill**: competitive matchup data and browser-generated exports.
- **PokémonMeta**: articles, cards, decks, win rates, sets, and related public
  entities.

The raw responses are kept separate from processed JSONL files so that the
normalization logic can be improved without repeatedly downloading the source
data.

## Project status

The data-collection and preparation foundation for Milestone 1 is implemented.
The following Milestone 2 and Milestone 3 components are not implemented yet:

- Unified cross-source schema and entity linking.
- Solr schema and indexing pipeline.
- Keyword retrieval experiments.
- Semantic/vector retrieval.
- Relevance judgments and retrieval evaluation.

## Repository structure

```text
.
├── extract_tcgapi_pokemon_cards.py   # TCG API set/card extractor
├── extract_trainerhill_dynamic.py    # Trainer Hill browser extractor
├── parse_trainerhill_dynamic.py      # Trainer Hill normalizer
├── extract_pokemonmeta_dynamic.py    # PokémonMeta page/API extractor
├── parse_pokemonmeta_dynamic.py      # PokémonMeta normalizer
├── data/
│   ├── raw/                          # Source responses and downloaded exports
│   └── processed/                    # Normalized JSONL datasets and metadata
├── projectRules.txt                  # PRI project requirements
└── pri2627-*.pdf                     # Course reference documents
```

All extraction scripts are standalone Python programs and use relative paths
from the repository root by default.

## Requirements

- Python 3.10 or newer.
- Internet access to the public source websites/APIs.
- Playwright and a Chromium browser for the Trainer Hill and PokémonMeta
  browser captures.

Create a virtual environment and install the browser dependency:

```bash
cd /home/lccaracol/PRI/FEUP-4Y1S-PRI
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install playwright
.venv/bin/playwright install chromium
```

The TCG API extractor uses only Python standard-library modules. The two
dynamic site extractors use Playwright.

## Running the pipelines

Run commands from the repository root. Each extractor overwrites its output
file for a new reproducible capture unless a different output path is supplied.

### 1. TCG API extraction

The TCG API extractor reads up to three credentials from environment
variables. Credentials are deliberately not stored in the repository.

```bash
export TCGAPI_KEY_1="tcg_live_9fb34fb743046412d3d6f00b7f548e1d8e8dd134"
export TCGAPI_KEY_2="tcg_live_8a5dde965304745f408c681749315f6098f9c16d"
export TCGAPI_KEY_3="tcg_live_9518afba9b4f28c97232c5953f81e8365becdbef"
```
remember, only 100 requests per day

At least one key is required. When multiple keys are configured, requests are
distributed in round-robin order. Do not commit keys, `.env` files, or shell
history containing credentials.

Run the complete set/card extraction:

```bash
.venv/bin/python extract_tcgapi_pokemon_cards.py
```

Default outputs:

```text
data/raw/tcgapi_pokemon_cards.jsonl
data/raw/tcgapi_pokemon_cards_metadata.json
```

Useful test and control options:

```bash
# Extract only a small number of sets as a connectivity test.
.venv/bin/python extract_tcgapi_pokemon_cards.py --max-sets 1

# Use a different page size or retry policy.
.venv/bin/python extract_tcgapi_pokemon_cards.py \
  --page-size 100 \
  --retries 3 \
  --retry-delay 2

# Resume-like bounded runs by selecting set catalogue pages.
.venv/bin/python extract_tcgapi_pokemon_cards.py \
  --sets-page 1 \
  --sets-pages 2
```

The metadata file records the extraction time, request counts by key, the
number of sets/cards observed, and failed sets. The API has a per-key quota;
check the metadata and the provider's current limits before starting a full
run.

### 2. Trainer Hill extraction and normalization

Trainer Hill is a Plotly Dash application, so its useful data is loaded by
the browser rather than being present in the initial HTML. The extractor:

- Reads the public sitemap.
- Visits same-domain public routes.
- Adds `game=PTCG`.
- Splits the requested historical range into yearly windows.
- Captures Dash callbacks, XHR/fetch responses, page text, and downloads.
- Activates available export controls.

Run the default historical capture from 2020 through today:

```bash
.venv/bin/python extract_trainerhill_dynamic.py
```

Normalize the capture:

```bash
.venv/bin/python parse_trainerhill_dynamic.py
```

Useful options:

```bash
# Capture a smaller test run.
.venv/bin/python extract_trainerhill_dynamic.py --max-pages 1 --wait 3

# Capture a specific historical range.
.venv/bin/python extract_trainerhill_dynamic.py \
  --start-date 2020-01-01 \
  --end-date 2025-12-31 \
  --window-years 1

# Use one broad window instead of yearly windows.
.venv/bin/python extract_trainerhill_dynamic.py --window-years 0

# Parse custom locations.
.venv/bin/python parse_trainerhill_dynamic.py \
  --input data/raw/trainerhill_dynamic_data.jsonl \
  --output-dir data/processed \
  --export-dir data/raw/trainerhill_exports
```

Default outputs:

```text
data/raw/trainerhill_dynamic_data.jsonl
data/raw/trainerhill_exports/
data/processed/trainerhill_matchups.jsonl
data/processed/trainerhill_components.jsonl
data/processed/trainerhill_export_rows.jsonl
data/processed/trainerhill_meta.jsonl
data/processed/trainerhill_cards.jsonl
data/processed/trainerhill_decks.jsonl
data/processed/trainerhill_table_rows.jsonl
data/processed/trainerhill_parsing_metadata.json
```

The raw capture includes provenance such as source URLs, request/response
content, retrieval timestamps, and historical window parameters.

### 3. PokémonMeta extraction and normalization

PokémonMeta exposes public API collections and also loads data in its web
pages. The extractor can capture both. For a complete collection-oriented
run, use API-only mode:

```bash
.venv/bin/python extract_pokemonmeta_dynamic.py --api-only
.venv/bin/python parse_pokemonmeta_dynamic.py
```

The API extractor discovers collection counts where available and paginates
large endpoints in batches. It stores each response in:

```text
data/raw/pokemonmeta_dynamic_data.jsonl
```

To capture pages as well as API traffic:

```bash
.venv/bin/python extract_pokemonmeta_dynamic.py
```

Useful options:

```bash
# Capture only the first two configured pages.
.venv/bin/python extract_pokemonmeta_dynamic.py --max-pages 2

# Use a custom raw output path.
.venv/bin/python extract_pokemonmeta_dynamic.py \
  --api-only \
  --output data/raw/pokemonmeta_test.jsonl

# Parse a custom raw file.
.venv/bin/python parse_pokemonmeta_dynamic.py \
  --input data/raw/pokemonmeta_dynamic_data.jsonl \
  --output-dir data/processed
```

The parser groups API responses by endpoint, extracts one entity per JSONL
line, adds source/provenance information, and deduplicates records using a
stable source identifier (`id`, `_id`, `slug`, or `url`) or a content
fingerprint.

## Current extraction results

The following counts are from the latest completed captures in this
repository. They describe the processed files, not necessarily the number of
records currently visible on the live websites.

### Trainer Hill

| Processed dataset | Records |
|---|---:|
| Matchups | 778 |
| Dash components | 11,269 |
| Export rows | 204 |
| Meta page captures | 7 |
| Card page captures | 7 |
| Deck page captures | 7 |
| Generic table rows | 0 |

### PokémonMeta

| Processed dataset | Records |
|---|---:|
| Articles | 1,056 |
| Top decks | 52,677 |
| Cards | 3,570 |
| Win rates | 3,101 |
| Sets | 61 |
| Deck types | 410 |
| Engines | 57 |
| Ranked types | 2 |
| Navigation tabs | 5 |
| Users | 100 |

The corresponding metadata files are:

```text
data/processed/trainerhill_parsing_metadata.json
data/processed/pokemonmeta_parsing_metadata.json
```

The TCG API extractor has been restored, but a complete TCG API capture must
be run with valid credentials. Its output is not included in the current
repository dataset.

## Raw data and GitHub file limits

Some generated PokémonMeta files are larger than GitHub's 100 MB per-file
limit. They are intentionally ignored by `.gitignore` but remain available
locally after extraction:

```text
data/raw/pokemonmeta_dynamic_data.jsonl
data/processed/pokemonmeta_articles.jsonl
data/processed/pokemonmeta_top_decks.jsonl
data/processed/pokemonmeta_winrates.jsonl
```

For team sharing, store these files in external project storage or Git LFS.
Do not force them into ordinary Git history. Other generated files may also
become large as the extraction ranges grow.

## Data interpretation and limitations

- The pipelines collect data currently exposed by the public sources. They
  cannot recover deleted records or historical versions no longer served.
- Trainer Hill uses the site's default filter state. All possible divisions,
  tournament types, platforms, and other combinations are not systematically
  enumerated.
- Trainer Hill PNG exports are preserved, but their charts are not converted
  into structured OCR data.
- Trainer Hill page/card/deck captures still contain Dash component structures
  and require additional domain-specific normalization.
- PokémonMeta may contain Pokémon TCG Pocket content. Physical Pokémon TCG
  and Pocket records must be separated before building the final collection.
- The sources are not yet cross-linked through shared card, set, deck, or
  archetype identifiers.
- API quotas, website changes, network failures, and browser rendering
  changes can affect future runs.

## Recommended execution order

For a fresh local extraction:

```bash
# 1. Capture and normalize PokémonMeta.
.venv/bin/python extract_pokemonmeta_dynamic.py --api-only
.venv/bin/python parse_pokemonmeta_dynamic.py

# 2. Capture and normalize Trainer Hill.
.venv/bin/python extract_trainerhill_dynamic.py
.venv/bin/python parse_trainerhill_dynamic.py

# 3. Capture TCG API cards after configuring API keys.
.venv/bin/python extract_tcgapi_pokemon_cards.py
```

The next preparation step is to define a unified document model that combines
card metadata, deck information, articles, matchups, and win rates while
retaining source provenance. That collection can then be converted into Solr
documents for the PRI retrieval milestones.

## Group members

- **Afonso Saraiva**: 202304461
- **Inês Francisco**: 202304726
- **Leonardo Carvalho**: 202307152
- **Miguel Pereira**: 202304387
