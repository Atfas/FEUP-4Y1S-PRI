# Pokémon TCG Search — PRI 2026/27, Milestone 1 (Data Preparation)

Course project for **Information Processing and Retrieval (PRI)**, M.EIC, FEUP.
This branch holds everything needed for the Milestone 1 delivery: the data pipeline,
the resulting document collection, the characterization code, the diagrams and the report.

The collection combines two sources:

- **Bulbapedia** ([MediaWiki API](https://bulbapedia.bulbagarden.net/w/api.php), CC BY-NC-SA 2.5):
  card, Pokémon species, illustrator and expansion pages.
- **TCGCSV** ([tcgcsv.com](https://tcgcsv.com)): daily mirror of TCGplayer market prices.

Result: 13,972 cards (18,420 prints, 20,327 attacks) linked to 1,027 species, 427 illustrators
and 221 expansions; 94% of cards have a market price (snapshot 2026-10-11).

## Repository structure

```text
.
├── main.py                 # runs the whole pipeline in order
├── fetching/               # download wikitext (Bulbapedia) and price CSVs (TCGCSV)
├── extracting/             # wikitext -> JSON (cards, entities, expansions)
├── processing/             # ids, entity linking, price matching, exploratory analysis
├── quality_check.py        # completeness / link checks
├── eda/characterize.py     # statistics + figures for the report -> eda/stats.json, report/figures/
├── search/                 # FINAL COLLECTION: cards, pokemon, artists, expansions + link/price reports
├── diagrams/PRI.drawio     # pipeline diagram and conceptual model (open with diagrams.net)
├── report/                 # ACM sigconf LaTeX report (main.tex, references.bib, figures/)
├── Makefile
└── pyproject.toml, uv.lock # pinned dependencies (Python 3.14, uv)
```

## How to reproduce

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
make pipeline   # uv run main.py   -> data/ (cache) and search/*.json
make eda        # uv run eda/characterize.py -> eda/stats.json, report/figures/*.pdf
make report     # needs LaTeX + acmart; otherwise upload report/ to Overleaf
```

Fetching is resumable: raw pages and CSVs are cached in `data/` (git-ignored) and skipped on re-runs.
Bulbapedia requests are batched (≤50 titles), delayed 2 s and respect `maxlag`.

## Pipeline

1. **Fetch** expansion list → expansion pages → card wikitext; then the Pokémon and artist pages the
   cards reference; then TCGCSV groups and `ProductsAndPrices.csv` per group.
2. **Extract** with `mwparserfromhell`: infobox fields, attacks/abilities (cost, damage, effect),
   Pokédex entries, gallery, release information, trivia, categories (Japanese-only data dropped).
3. **Process**: stable slug ids (`card:abra-151-63`), card ↔ species/artist/expansion links with stub
   records for names without a page, prints with expansion/illustrator/image, flattened `rules_text`.
4. **Merge prices**: products matched by card name + number, TCGCSV groups mapped to expansions by
   vote; ambiguous products are reported, never guessed.

See `diagrams/PRI.drawio` for the diagram and `search/links_report.json` / `search/price_report.json`
for what was linked, stubbed or left unmatched.

## Other sources explored

Trainer Hill (archetype win rates only), PokémonMeta (TCG Pocket, not the physical TCG) and the
Pokémon TCG API (100 requests/day) were evaluated but are not part of the collection.
Their extractors and captures remain on branch `leo`.

## Group

- Afonso Saraiva — 202304461
- Inês Francisco — 202304726
- Leonardo Carvalho — 202307152
- Miguel Pereira — 202304387
