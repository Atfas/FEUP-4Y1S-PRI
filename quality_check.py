"""Generate completeness, relationship, and sample-coverage statistics."""
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path


SAMPLE_SIZE = 1000
SAMPLE_SEED = 42


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
        for item in value:
            for field, count in _count_nulls(item, f"{path}[]").items():
                counts[field] = counts.get(field, 0) + count
        return counts
    return {}


def _count_empty_fields(records):
    counts = {}
    field_names = {key for record in records if isinstance(record, dict) for key in record}
    for field in field_names:
        counts[field] = sum(
            field not in record
            or record[field] is None
            or record[field] == ""
            or record[field] == []
            or record[field] == {}
            for record in records
        )
    return {field: count for field, count in counts.items() if count}


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


def _card_entities(cards):
    artist_names = set()
    pokemon_names = set()
    expansion_names = set()
    source_sets = set()
    artist_links = 0
    pokemon_links = 0
    expansion_links = 0

    for card in cards:
        artists = {name.strip() for name in card.get("artists", []) if isinstance(name, str) and name.strip()}
        pokemon = {name.strip() for name in _pokemon_names(card) if isinstance(name, str) and name.strip()}
        expansions = {
            print_info["expansion"].strip()
            for print_info in card.get("prints", [])
            if isinstance(print_info.get("expansion"), str) and print_info["expansion"].strip()
        }
        artist_names.update(artists)
        pokemon_names.update(pokemon)
        expansion_names.update(expansions)
        artist_links += len(artists)
        pokemon_links += len(pokemon)
        expansion_links += len(expansions)

        source_set = card.get("set")
        if isinstance(source_set, str) and source_set.strip():
            source_sets.add(source_set.strip())

    return {
        "artists": artist_names,
        "pokemon": pokemon_names,
        "expansions": expansion_names,
        "source_sets": source_sets,
        "artist_links": artist_links,
        "pokemon_links": pokemon_links,
        "expansion_links": expansion_links,
    }


def _indexed_title_map(index, valid_titles):
    return {
        _normalized(name): set(titles).intersection(valid_titles)
        for name, titles in index.items()
    }


def _values_at_path(value, parts):
    if not parts:
        if isinstance(value, str) and value.strip():
            yield value.strip()
        elif isinstance(value, list):
            for item in value:
                yield from _values_at_path(item, ())
        return
    if isinstance(value, list):
        for item in value:
            yield from _values_at_path(item, parts)
    elif isinstance(value, dict) and parts[0] in value:
        yield from _values_at_path(value[parts[0]], parts[1:])


def _text_profile(records, field_path):
    lengths = []
    for record in records:
        text = " ".join(_values_at_path(record, field_path.split(".")))
        if text:
            lengths.append(len(text))
    if not lengths:
        return len(records), 0, 0, 0, 0, 0
    p90_index = max(0, (9 * len(lengths) + 9) // 10 - 1)
    ordered = sorted(lengths)
    return (
        len(records),
        len(lengths),
        statistics.median(lengths),
        round(statistics.mean(lengths)),
        ordered[p90_index],
        max(lengths),
    )


def _duplicate_groups(records, field):
    groups = {}
    for record in records:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            groups.setdefault(_normalized(value), []).append(value.strip())
    duplicates = [values for values in groups.values() if len(values) > 1]
    return duplicates


def _text_duplicate_stats(records, field_path):
    counts = {}
    examples = {}
    for record in records:
        text = " ".join(_values_at_path(record, field_path.split(".")))
        normalized = " ".join(text.split()).casefold()
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1
            examples.setdefault(normalized, text)
    repeated = [(text, count) for text, count in counts.items() if count > 1]
    repeated.sort(key=lambda item: (-item[1], item[0]))
    return len(repeated), sum(count - 1 for _, count in repeated), [
        (examples[text], count) for text, count in repeated[:5]
    ]


def _longest_texts(records, field_path, limit=5):
    texts = []
    for record in records:
        text = " ".join(_values_at_path(record, field_path.split(".")))
        if text:
            texts.append((len(text), record.get("title", record.get("name", "(unnamed)")), text))
    return sorted(texts, reverse=True)[:limit]


def _link_distribution(links_by_name):
    counts = [len(titles) for titles in links_by_name.values()]
    if not counts:
        return 0, 0, 0, 0, 0, []
    ordered = sorted(counts)
    p90_index = max(0, (9 * len(ordered) + 9) // 10 - 1)
    return (
        round(statistics.mean(counts), 2),
        statistics.median(counts),
        ordered[p90_index],
        max(counts),
        sum(sorted(counts, reverse=True)[:10]) / sum(counts),
        sorted(links_by_name.items(), key=lambda item: (-len(item[1]), item[0].casefold()))[:10],
    )


def _sample_statistics(cards, corpus_entities, expansion_names):
    sample = random.Random(SAMPLE_SEED).sample(cards, min(SAMPLE_SIZE, len(cards)))
    sample_entities = _card_entities(sample)
    matched_expansions = {
        name for name in sample_entities["expansions"]
        if _normalized(name) in expansion_names
    }
    unmatched_prints = sample_entities["expansions"] - matched_expansions

    def coverage(sample_set, corpus_set):
        return f"{len(sample_set) / len(corpus_set):.1%}" if corpus_set else "n/a"

    return {
        "card_count": len(sample),
        "source_sets": len(sample_entities["source_sets"]),
        "artists": len(sample_entities["artists"]),
        "artist_coverage": coverage(sample_entities["artists"], corpus_entities["artists"]),
        "pokemon": len(sample_entities["pokemon"]),
        "pokemon_coverage": coverage(sample_entities["pokemon"], corpus_entities["pokemon"]),
        "matched_expansions": len(matched_expansions),
        "expansion_coverage": coverage(matched_expansions, corpus_entities["matched_expansions"]),
        "unmatched_prints": sorted(unmatched_prints),
    }


def _markdown_table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def build_quality_report(data_dir="data", output_path=None):
    """Write a Markdown quality report and return its path."""
    data_dir = Path(data_dir)
    cards = _read_json(data_dir / "cards.json")
    artists = _read_json(data_dir / "artist.json")
    pokemon = _read_json(data_dir / "pokemon.json")
    expansions = _read_json(data_dir / "expansions.json")
    artist_index = _read_json(data_dir / "_indexes" / "artists.json")
    pokemon_index = _read_json(data_dir / "_indexes" / "pokemon.json")

    card_titles = {card["title"] for card in cards}
    artist_title_map = _indexed_title_map(artist_index, card_titles)
    pokemon_title_map = _indexed_title_map(pokemon_index, card_titles)
    expansion_names = {_normalized(expansion["name"]) for expansion in expansions}
    corpus_entities = _card_entities(cards)
    artist_documents = {_normalized(artist.get("name", "")) for artist in artists}
    pokemon_documents = {_normalized(entry.get("name", "")) for entry in pokemon}
    dangling_artists = sorted(
        (name for name in corpus_entities["artists"] if _normalized(name) not in artist_documents),
        key=str.casefold,
    )
    dangling_pokemon = sorted(
        (name for name in corpus_entities["pokemon"] if _normalized(name) not in pokemon_documents),
        key=str.casefold,
    )
    dangling_expansions = sorted(
        (name for name in corpus_entities["expansions"] if _normalized(name) not in expansion_names),
        key=str.casefold,
    )
    artist_title_map = {
        name: titles for name, titles in artist_title_map.items() if titles
    }
    pokemon_title_map = {
        name: titles for name, titles in pokemon_title_map.items() if titles
    }
    expansion_title_map = {}
    for card in cards:
        for print_info in card.get("prints", []):
            name = print_info.get("expansion")
            if isinstance(name, str) and name.strip():
                expansion_title_map.setdefault(_normalized(name), set()).add(card["title"])
    expansion_title_map = {
        name: titles for name, titles in expansion_title_map.items() if name in expansion_names
    }
    matched_expansions = {
        name for name in corpus_entities["expansions"]
        if _normalized(name) in expansion_names
    }
    corpus_entities["matched_expansions"] = matched_expansions

    cards_with_artists = 0
    cards_with_pokemon = 0
    cards_with_expansions = 0
    cards_with_any_connection = 0
    for card in cards:
        title = card["title"]
        has_artist = any(
            title in artist_title_map.get(_normalized(name), set())
            for name in card.get("artists", [])
        )
        has_pokemon = any(
            title in pokemon_title_map.get(_normalized(name), set())
            for name in _pokemon_names(card)
        )
        has_expansion = any(
            _normalized(print_info.get("expansion", "")) in expansion_names
            for print_info in card.get("prints", [])
        )
        cards_with_artists += has_artist
        cards_with_pokemon += has_pokemon
        cards_with_expansions += has_expansion
        cards_with_any_connection += has_artist or has_pokemon or has_expansion

    unconnected_cards = len(cards) - cards_with_any_connection
    unconnected_artists = sum(
        not artist_title_map.get(_normalized(artist.get("name", "")))
        for artist in artists
    )
    unconnected_pokemon = sum(
        not pokemon_title_map.get(_normalized(entry.get("name", "")))
        for entry in pokemon
    )
    print_expansion_names = {
        _normalized(name) for name in corpus_entities["expansions"]
    }
    unconnected_expansions = sum(
        _normalized(expansion.get("name", "")) not in print_expansion_names
        for expansion in expansions
    )
    datasets = [
        ("cards.json", cards, unconnected_cards),
        ("artist.json", artists, unconnected_artists),
        ("pokemon.json", pokemon, unconnected_pokemon),
        ("expansions.json", expansions, unconnected_expansions),
    ]

    null_counts_by_dataset = {
        name: _count_nulls(records)
        for name, records, _ in datasets
    }
    rows = [
        (name, len(records), sum(null_counts_by_dataset[name].values()), unconnected)
        for name, records, unconnected in datasets
    ]

    lines = [
        "# Data quality report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Dataset overview",
        "",
        _markdown_table(
            ["JSON file", "Documents", "Null values", "Unconnected documents"],
            rows,
        ),
        "",
        "Unconnected cards have no artist, Pokémon, or expansion link. Artist and Pokémon "
        "connections use the generated indexes; expansion connections match print names "
        "against `expansions.json`.",
        "",
        "## Field completeness",
        "",
    ]

    for name, records, _ in datasets:
        empty_counts = _count_empty_fields(records)
        lines.extend((f"### `{name}`", ""))
        if empty_counts:
            lines.append(_markdown_table(["Field", "Missing, null, or empty documents"], sorted(empty_counts.items())))
        else:
            lines.append("No missing or empty top-level fields.")
        null_counts = null_counts_by_dataset[name]
        lines.extend(("", "Null values by field path:", ""))
        if null_counts:
            lines.append(_markdown_table(["Field path", "Null values"], sorted(null_counts.items())))
        else:
            lines.append("None.")
        lines.append("")

    text_fields = [
        ("cards.json", cards, "title"),
        ("cards.json", cards, "card_text.name"),
        ("cards.json", cards, "card_text.effect"),
        ("cards.json", cards, "pokedex.dex"),
        ("cards.json", cards, "release_information.text"),
        ("cards.json", cards, "trivia.text"),
        ("artist.json", artists, "description"),
        ("artist.json", artists, "artwork"),
        ("pokemon.json", pokemon, "biology"),
        ("pokemon.json", pokemon, "pokedex_entries.entry"),
        ("expansions.json", expansions, "name"),
        ("expansions.json", expansions, "blurb"),
        ("expansions.json", expansions, "information"),
    ]
    text_rows = []
    for dataset_name, records, field_path in text_fields:
        total, nonempty, median, mean, p90, maximum = _text_profile(records, field_path)
        text_rows.append((
            f"`{dataset_name}` · `{field_path}`",
            f"{nonempty}/{total}",
            f"{(total - nonempty) / total:.1%}" if total else "n/a",
            median,
            mean,
            p90,
            maximum,
        ))
    lines.extend((
        "## Searchable text profile",
        "",
        "Text lengths are character counts after trimming. Empty rate is the share of records "
        "with no text at the listed field path. Nested text arrays are combined per document.",
        "",
        _markdown_table(
            ["Field", "Non-empty documents", "Empty rate", "Median chars", "Mean chars", "P90 chars", "Max chars"],
            text_rows,
        ),
        "",
    ))

    inspect_fields = [
        ("Card rules text", cards, "card_text.effect"),
        ("Card release information", cards, "release_information.text"),
        ("Card trivia", cards, "trivia.text"),
        ("Pokémon biology", pokemon, "biology"),
        ("Pokédex entries", pokemon, "pokedex_entries.entry"),
        ("Artist descriptions", artists, "description"),
        ("Expansion information", expansions, "information"),
    ]
    longest_rows = []
    repeated_rows = []
    repeated_examples = []
    for label, records, field_path in inspect_fields:
        longest_rows.extend(
            (label, title, length, text[:240] + ("…" if len(text) > 240 else ""))
            for length, title, text in _longest_texts(records, field_path, limit=3)
        )
        group_count, duplicate_count, examples = _text_duplicate_stats(records, field_path)
        repeated_rows.append((label, group_count, duplicate_count))
        repeated_examples.extend(
            f"- `{label}` ({count} records): {text[:180]}{'…' if len(text) > 180 else ''}"
            for text, count in examples[:2]
        )
    lines.extend((
        "## Text inspection signals",
        "",
        "The longest extracted texts are listed as review candidates, not automatically classified "
        "as errors. Repeated-text counts use whitespace/case-normalized, per-document text.",
        "",
        _markdown_table(
            ["Text field", "Record", "Characters", "Longest-text excerpt (up to 240 chars)"],
            longest_rows,
        ),
        "",
        _markdown_table(
            ["Text field", "Repeated text groups", "Extra records in repeated groups"],
            repeated_rows,
        ),
        "",
    ))
    if repeated_examples:
        lines.extend(("Examples of repeated text:", "", *repeated_examples, ""))

    duplicate_specs = [
        ("cards.json", cards, "title"),
        ("artist.json", artists, "name"),
        ("pokemon.json", pokemon, "name"),
        ("expansions.json", expansions, "name"),
    ]
    duplicate_rows = []
    duplicate_examples = []
    for dataset_name, records, key_field in duplicate_specs:
        groups = _duplicate_groups(records, key_field)
        duplicate_rows.append((
            f"`{dataset_name}` · `{key_field}`",
            len(groups),
            sum(len(group) - 1 for group in groups),
        ))
        for group in groups[:5]:
            duplicate_examples.append(
                f"- `{dataset_name}` `{key_field}`: {', '.join(group[:5])}"
            )
    lines.extend((
        "## Duplicate identifiers",
        "",
        "Duplicate groups compare identifiers after whitespace normalization and case-folding. "
        "The duplicate-record count excludes the first record in each group.",
        "",
        _markdown_table(["Identifier", "Duplicate groups", "Extra duplicate records"], duplicate_rows),
        "",
    ))
    if duplicate_examples:
        lines.extend(("Examples:", *duplicate_examples, ""))

    distribution_rows = []
    distribution_examples = []
    for label, links_by_name in (
        ("Artist → cards", artist_title_map),
        ("Pokémon → cards", pokemon_title_map),
        ("Expansion → cards", expansion_title_map),
    ):
        mean, median, p90, maximum, top_ten_share, top = _link_distribution(links_by_name)
        distribution_rows.append((
            label, len(links_by_name), mean, median, p90, maximum, f"{top_ten_share:.1%}",
        ))
        distribution_examples.extend(
            f"- `{label}` **{name}**: {len(titles)} cards"
            for name, titles in top
        )
    lines.extend((
        "## Cards per linked entity",
        "",
        "Counts use links to card titles present in `cards.json`; expansion links come from "
        "card print names matched to `expansions.json`.",
        "",
        _markdown_table(
            ["Entity relationship", "Entities", "Mean cards", "Median cards", "P90 cards", "Max cards", "Top-10 share of links"],
            distribution_rows,
        ),
        "",
        "Most-linked entities:",
        "",
        *distribution_examples,
        "",
    ))

    total_cards = len(cards)
    relationship_rows = [
        ("Card–artist", corpus_entities["artist_links"], len(corpus_entities["artists"]), cards_with_artists),
        ("Card–Pokémon", corpus_entities["pokemon_links"], len(corpus_entities["pokemon"]), cards_with_pokemon),
        ("Card–print expansion", corpus_entities["expansion_links"], len(corpus_entities["expansions"]), cards_with_expansions),
    ]
    lines.extend((
        "## Relationship coverage",
        "",
        _markdown_table(
            ["Relationship", "Links", "Distinct referenced names", "Cards with at least one"],
            [
                (label, link_count, entity_count, f"{card_count}/{total_cards}")
                for label, link_count, entity_count, card_count in relationship_rows
            ],
        ),
        "",
        f"Cards represent **{len(corpus_entities['source_sets'])} distinct source folders**. "
        f"Of {len(corpus_entities['expansions'])} distinct print labels, "
        f"**{len(matched_expansions)}** match an expansion record and "
        f"**{len(corpus_entities['expansions']) - len(matched_expansions)}** do not. "
        "Unmatched labels can be promos or other products, not necessarily extraction errors.",
        "",
    ))

    lines.extend((
        "## Missing referenced records",
        "",
        "These are distinct names referenced from card records that have no matching record "
        "in the corresponding entity JSON. Unmatched print labels may be promos or products, "
        "not necessarily errors.",
        "",
        _markdown_table(
            ["Reference type", "Distinct names without a record", "Total distinct card references"],
            [
                ("Artist", len(dangling_artists), len(corpus_entities["artists"])),
                ("Pokémon", len(dangling_pokemon), len(corpus_entities["pokemon"])),
                ("Print / expansion label", len(dangling_expansions), len(corpus_entities["expansions"])),
            ],
        ),
        "",
    ))
    for label, names in (
        ("Artists", dangling_artists),
        ("Pokémon", dangling_pokemon),
        ("Print labels", dangling_expansions),
    ):
        if names:
            lines.extend((f"**{label} without records:** " + ", ".join(names[:30]) +
                          (" …" if len(names) > 30 else ""), ""))

    card_groups = {
        "Pokémon-linked cards": [
            card for card in cards
            if card.get("pokedex") or card.get("infobox", {}).get("species")
        ],
        "Other cards": [
            card for card in cards
            if not card.get("pokedex") and not card.get("infobox", {}).get("species")
        ],
    }
    completeness_rows = []
    for label, group in card_groups.items():
        count = len(group)
        with_dex = sum(bool(card.get("pokedex")) for card in group)
        with_card_text = sum(bool(card.get("card_text")) for card in group)
        completeness_rows.append((
            label,
            count,
            f"{with_dex}/{count} ({with_dex / count:.1%})" if count else "0",
            f"{with_card_text}/{count} ({with_card_text / count:.1%})" if count else "0",
        ))
    lines.extend((
        "## Card completeness by record kind",
        "",
        "Pokémon-linked cards are identified by a Pokédex entry or infobox species field; "
        "the remaining records are grouped as other cards. This is a proxy based on extracted fields.",
        "",
        _markdown_table(
            ["Record group", "Cards", "With Pokédex entry", "With card text"],
            completeness_rows,
        ),
        "",
    ))

    sample = _sample_statistics(cards, corpus_entities, expansion_names)
    lines.extend(("## Reproducible random card sample", ""))
    lines.append(
        f"Sampled **{sample['card_count']}** of **{total_cards}** card documents "
        f"using seed `{SAMPLE_SEED}`."
    )
    lines.extend((
        "",
        _markdown_table(
            ["Measure", "Sample", "Coverage of card-referenced corpus"],
            [
                ("Source folders", sample["source_sets"], "—"),
                ("Artists", sample["artists"], sample["artist_coverage"]),
                ("Pokémon", sample["pokemon"], sample["pokemon_coverage"]),
                ("Matched expansions", sample["matched_expansions"], sample["expansion_coverage"]),
            ],
        ),
        "",
        f"Distinct unmatched print labels in the sample: **{len(sample['unmatched_prints'])}**.",
    ))
    if sample["unmatched_prints"]:
        lines.extend(("", "Examples: " + ", ".join(sample["unmatched_prints"][:30]) + "."))
    lines.append("")

    if output_path is None:
        output_path = data_dir.parent / "quality_report.md"
    else:
        output_path = Path(output_path)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    build_quality_report()
