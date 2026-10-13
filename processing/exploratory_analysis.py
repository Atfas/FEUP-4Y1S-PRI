"""Clean and profile the search-ready Bulbapedia data for exploratory analysis."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_DIR / "search"
OUTPUT_DIR = Path(__file__).resolve().parent / "eda_output"

DATASETS = ("cards", "pokemon", "artists", "expansions")
ABBREVIATION_EXPANSIONS = {
    "TCG": "trading card game",
}
ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")
TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am",
    "an", "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "could", "did",
    "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "get", "got", "had", "has", "have", "having", "he", "her",
    "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it",
    "its", "itself", "just", "may", "me", "might", "more", "most", "must",
    "my", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "our", "out", "over", "own", "same", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "us", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "why", "will", "with", "would", "you", "your",
    "bulbapedia", "card", "cards", "game", "pokemon", "pokémon", "set", "tcg",
    "trading",
}


def read_dataset(name: str) -> list[dict]:
    path = INPUT_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Required search dataset was not found: {path}")
    with path.open(encoding="utf-8") as file:
        records = json.load(file)
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError(f"Expected {path} to contain a JSON array of objects")
    return records


def _clean_markup(value: str) -> str:
    # The entity extractor can leave a standalone section marker in its text.
    value = re.sub(r"(?im)^\s*section\s*$", "", value)
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _string_values(item)]
    return []


def _record_text(dataset: str, record: dict) -> str:
    if dataset == "cards":
        values = [
            record.get("title"),
            record.get("release_information"),
            record.get("trivia"),
            record.get("tags", []),
        ]
        for item in record.get("card_text", []):
            if isinstance(item, dict):
                values.extend(item.get(field) for field in ("name", "effect", "text"))
    elif dataset == "pokemon":
        values = [record.get("name"), record.get("biology")]
        values.extend(
            entry.get("entry")
            for entry in record.get("pokedex_entries", [])
            if isinstance(entry, dict)
        )
    elif dataset == "artists":
        values = [record.get("name"), record.get("description"), record.get("artwork")]
    else:
        values = [record.get("name"), record.get("blurb"), record.get("information")]

    return " ".join(
        cleaned
        for value in values
        for text in _string_values(value)
        if (cleaned := _clean_markup(text))
    )


def _expand_abbreviations(text: str) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()
    for abbreviation, expanded in ABBREVIATION_EXPANSIONS.items():
        pattern = re.compile(rf"(?<!\w){re.escape(abbreviation)}(?!\w)", re.IGNORECASE)
        text, count = pattern.subn(expanded, text)
        counts[abbreviation] += count
    return text.casefold(), counts


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if len(token) > 1 and token not in STOPWORDS
    ]


def build_corpus() -> tuple[pd.DataFrame, Counter[str], dict[str, list[str]]]:
    rows = []
    abbreviation_counts: Counter[str] = Counter()
    abbreviation_examples: dict[str, list[str]] = defaultdict(list)

    for dataset in DATASETS:
        for record in read_dataset(dataset):
            title = str(record.get("title") or record.get("name") or record.get("id") or "")
            source_text = _record_text(dataset, record)
            for abbreviation in ACRONYM_PATTERN.findall(source_text):
                abbreviation_counts[abbreviation] += 1
                if len(abbreviation_examples[abbreviation]) < 5:
                    abbreviation_examples[abbreviation].append(title)

            normalized_text, expanded = _expand_abbreviations(source_text)
            rows.append(
                {
                    "dataset": dataset,
                    "id": str(record.get("id", "")),
                    "title": title,
                    "source_text": source_text,
                    "normalized_text": normalized_text,
                    "character_count": len(normalized_text),
                    "token_count": len(_tokens(normalized_text)),
                    "abbreviations_expanded": sum(expanded.values()),
                    "contains_html_markup": bool(re.search(r"</?[A-Za-z][^>]*>", source_text)),
                }
            )

    return pd.DataFrame(rows), abbreviation_counts, abbreviation_examples


def extract_keywords(corpus: pd.DataFrame) -> pd.DataFrame:
    term_frequency: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    for text in corpus["normalized_text"]:
        tokens = _tokens(text)
        term_frequency.update(tokens)
        document_frequency.update(set(tokens))

    document_count = len(corpus)
    rows = [
        {
            "keyword": term,
            "term_frequency": frequency,
            "document_frequency": document_frequency[term],
            "tf_idf_score": round(
                frequency * (math.log((document_count + 1) / (document_frequency[term] + 1)) + 1),
                4,
            ),
        }
        for term, frequency in term_frequency.items()
    ]
    return pd.DataFrame(rows).sort_values(
        ["tf_idf_score", "term_frequency", "keyword"],
        ascending=[False, False, True],
    )


def _markdown_table(headers: list[str], rows: list[tuple]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(value).replace("|", r"\|").replace("\n", " ") for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(
    corpus: pd.DataFrame,
    keywords: pd.DataFrame,
    abbreviation_counts: Counter[str],
    abbreviation_examples: dict[str, list[str]],
) -> None:
    summary = (
        corpus.groupby("dataset", sort=False)
        .agg(
            records=("id", "size"),
            records_with_text=("normalized_text", lambda values: values.str.strip().ne("").sum()),
            mean_characters=("character_count", "mean"),
            median_characters=("character_count", "median"),
            max_characters=("character_count", "max"),
            html_residue_records=("contains_html_markup", "sum"),
        )
        .reset_index()
    )
    duplicate_titles = (
        corpus.assign(title_key=corpus["title"].str.casefold().str.replace(r"\s+", " ", regex=True))
        .duplicated(subset=["dataset", "title_key"])
        .sum()
    )
    expanded_count = int(corpus["abbreviations_expanded"].sum())
    known_abbreviations = set(ABBREVIATION_EXPANSIONS)
    abbreviation_rows = [
        (
            abbreviation,
            count,
            "expanded to " + ABBREVIATION_EXPANSIONS[abbreviation]
            if abbreviation in known_abbreviations
            else "review",
            ", ".join(abbreviation_examples[abbreviation][:3]),
        )
        for abbreviation, count in sorted(
            abbreviation_counts.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
    top_keywords = [
        (row.keyword, row.term_frequency, row.document_frequency, row.tf_idf_score)
        for row in keywords.head(30).itertuples(index=False)
    ]
    summary_rows = [
        (
            row.dataset,
            row.records,
            row.records_with_text,
            f"{row.mean_characters:.1f}",
            f"{row.median_characters:.1f}",
            row.max_characters,
            row.html_residue_records,
        )
        for row in summary.itertuples(index=False)
    ]

    content = "\n".join(
        [
            "# Exploratory data analysis",
            "",
            f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
            "",
            "Source: the search-ready JSON collections in `../search/`. The source files are not modified.",
            "HTML markup is stripped, standalone extractor section markers are removed, and derived text is case-folded.",
            f"{expanded_count} known abbreviation occurrence(s) were expanded. Unknown uppercase tokens are review candidates, not auto-corrected.",
            "",
            "## Collection and text profile",
            "",
            _markdown_table(
                [
                    "Collection", "Records", "With text", "Mean chars", "Median chars",
                    "Max chars", "HTML-markup records",
                ],
                summary_rows,
            ),
            "",
            f"Repeated titles after case/whitespace normalization: **{duplicate_titles}**.",
            "",
            "## Keyword candidates",
            "",
            "Ranked by total term frequency multiplied by smoothed inverse document frequency. Common English and dataset-generic terms are excluded.",
            "",
            _markdown_table(
                ["Keyword", "Term frequency", "Document frequency", "TF-IDF score"],
                top_keywords,
            ),
            "",
            "## Abbreviation candidates",
            "",
            "Known expansions are applied only to the derived normalized text. Other uppercase tokens may be abbreviations, card-series labels, or proper-name codes; inspect the examples before expanding them.",
            "",
            _markdown_table(
                ["Token", "Occurrences", "Action", "Example records"],
                abbreviation_rows,
            ),
            "",
            "## Generated files",
            "",
            "- `cleaned_text.csv`: case-preserving cleaned text and normalized text per record.",
            "- `keywords.csv`: keyword counts, document frequency, and corpus TF-IDF ranking.",
            "- `abbreviation_candidates.csv`: uppercase-token counts and sample record titles.",
            "- `eda_report.md`: this summary.",
            "",
        ]
    )
    (OUTPUT_DIR / "eda_report.md").write_text(content, encoding="utf-8")


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    corpus, abbreviation_counts, abbreviation_examples = build_corpus()
    keywords = extract_keywords(corpus)

    corpus.to_csv(OUTPUT_DIR / "cleaned_text.csv", index=False, encoding="utf-8")
    keywords.to_csv(OUTPUT_DIR / "keywords.csv", index=False, encoding="utf-8")
    pd.DataFrame(
        [
            {
                "token": abbreviation,
                "occurrences": count,
                "expanded_to": ABBREVIATION_EXPANSIONS.get(abbreviation, ""),
                "example_records": " | ".join(abbreviation_examples[abbreviation]),
            }
            for abbreviation, count in sorted(
                abbreviation_counts.items(), key=lambda item: (-item[1], item[0].casefold())
            )
        ],
        columns=["token", "occurrences", "expanded_to", "example_records"],
    ).to_csv(OUTPUT_DIR / "abbreviation_candidates.csv", index=False, encoding="utf-8")
    write_report(corpus, keywords, abbreviation_counts, abbreviation_examples)
    print(f"EDA artifacts written to {OUTPUT_DIR}")


if __name__ == "__main__":
    run()
