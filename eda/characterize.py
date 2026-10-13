"""Characterize the final card collection (search/*.json).

Writes eda/stats.json (all numbers quoted in the report) and report/figures/*.pdf.
Run from the PRI root:  .venv/bin/python eda/characterize.py
"""
import collections
import json
import re
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "search"
FIG = ROOT / "report" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

cards = json.load(open(DATA / "cards.json"))
pokemon = json.load(open(DATA / "pokemon.json"))
artists = json.load(open(DATA / "artists.json"))
expansions = json.load(open(DATA / "expansions.json"))

TEXT_FIELDS = ["rules_text", "release_information", "trivia"]
STOP = set("""a an the of to and or in on for is it its this that be by as at with from your
your's you if each any can are was were has have not this card cards pokémon pokemon
s don't do does than then into up all their them they which more one his her""".split())


def words(t):
    return re.findall(r"[a-zà-ÿé']+", (t or "").lower())


def empty(v):
    return v in (None, "", [], {})


def card_category(c):
    """Collapse the 46 raw `kind` values into the three game categories."""
    if c["subtype"] in {"Item", "Supporter", "Stadium", "Pokémon Tool", "Technical Machine",
                        "Rocket's Secret Machine", "Goldenrod Game Corner"} or \
       c["kind"] in {"trainer", "old trainer", "supporter", "stadium", "goods"}:
        return "Trainer"
    if c["pokemon"]:
        return "Pokémon"
    return "Other/Energy"


# ---- release year per expansion, parsed from the Bulbapedia infobox prose
def expansion_year(e):
    txt = e.get("information") or ""
    m = re.search(r"released[^.]{0,80}?\b((?:19|20)\d{2})\b", txt)
    return int(m.group(1)) if m else None


exp_year = {e["id"]: expansion_year(e) for e in expansions}


def card_year(c):
    ys = [exp_year.get(x["id"]) for x in c["expansions"]]
    ys = [y for y in ys if y]
    return min(ys) if ys else None


stats = {}
stats["counts"] = {"cards": len(cards), "pokemon": len(pokemon), "artists": len(artists),
                   "expansions": len(expansions),
                   "prints": sum(len(c["prints"]) for c in cards),
                   "price_rows": sum(len(p["prices"]) for c in cards for p in c["prints"])}
keys = list(cards[0].keys())
stats["card_field_missing_pct"] = {k: round(100 * sum(empty(c.get(k)) for c in cards) / len(cards), 1) for k in keys}
stats["raw_kind_values"] = len({c["kind"] for c in cards})
cat = collections.Counter(card_category(c) for c in cards)
stats["category"] = dict(cat)
stats["type"] = dict(collections.Counter(c["type"] or "None" for c in cards).most_common())
stats["prints_per_card"] = dict(sorted(collections.Counter(len(c["prints"]) for c in cards).items()))

# ---- text metrics
for f in TEXT_FIELDS:
    L = [len(words(c.get(f))) for c in cards]
    nz = [x for x in L if x]
    stats[f"words_{f}"] = {"non_empty": len(nz), "mean_non_empty": round(st.mean(nz), 1),
                           "median_non_empty": st.median(nz), "max": max(L)}
doc_len = [sum(len(words(c.get(f))) for f in TEXT_FIELDS + ["name"]) for c in cards]
stats["doc_words"] = {"mean": round(st.mean(doc_len), 1), "median": st.median(doc_len),
                      "max": max(doc_len), "total_tokens": sum(doc_len)}
stats["rules_text_name_only_pct"] = round(100 * sum(1 for c in cards if ":" not in c["rules_text"]
                                                    and len(words(c["rules_text"])) <= 4) / len(cards), 1)
vocab = collections.Counter(w for c in cards for f in TEXT_FIELDS for w in words(c.get(f)))
stats["vocabulary_size"] = len(vocab)
stats["hapax_legomena"] = sum(1 for v in vocab.values() if v == 1)
rt = collections.Counter(w for c in cards for w in words(c["rules_text"]) if w not in STOP and len(w) > 2)
stats["top_rules_terms"] = rt.most_common(25)
bi = collections.Counter()
for c in cards:
    ws = [w for w in words(c["rules_text"]) if w not in STOP]
    bi.update(zip(ws, ws[1:]))
stats["top_rules_bigrams"] = [(" ".join(k), v) for k, v in bi.most_common(20)]

# ---- mechanic keyword coverage (ties characterization to the information needs)
MECH = {
    "discard pile": r"discard pile",
    "draw cards": r"\bdraw \d+|\bdraw (?:a|up to|cards)",
    "search deck": r"search your deck",
    "energy attach/move": r"attach .{0,30}energy|move .{0,30}energy",
    "heal": r"\bheal\b",
    "special conditions": r"asleep|burned|confused|paralyzed|poisoned",
    "coin flip": r"flip (?:a|\d+) coins?",
}
stats["mechanics_pct"] = {k: round(100 * sum(1 for c in cards if re.search(p, c["rules_text"], re.I)) / len(cards), 1)
                          for k, p in MECH.items()}

# ---- artists / expansions / prices
ac = collections.Counter(a["name"].strip() for c in cards for a in c["artists"])
stats["top_artists"] = ac.most_common(10)
stats["artists_with_page"] = sum(1 for a in artists if a.get("has_page"))
stats["expansions_with_page"] = sum(1 for e in expansions if e.get("has_page"))
stats["expansions_with_year"] = sum(1 for y in exp_year.values() if y)
prices = [c["market_price_min"] for c in cards if c.get("market_price_min") is not None]
stats["price_min_usd"] = {"n": len(prices), "median": st.median(prices), "mean": round(st.mean(prices), 2),
                          "p95": sorted(prices)[int(0.95 * len(prices))], "max": max(prices)}
stats["most_expensive"] = [(c["title"], c["market_price_max"]) for c in
                           sorted(cards, key=lambda c: c.get("market_price_max") or 0, reverse=True)[:5]]

years = collections.Counter(card_year(c) for c in cards)
stats["cards_with_year"] = sum(v for k, v in years.items() if k)

# ---- structured card text (attacks / abilities), available since the bulbapedia-branch data
ATTACK_KINDS = {"attack", "gxattack"}
ABILITY_KINDS = {"ability", "poké-body", "poké-power", "pokémon power"}


def damage(entry):
    """'120+' -> 120, '30×' -> 30, '' -> None."""
    m = re.match(r"\d+", str(entry.get("damage") or ""))
    return int(m.group()) if m else None


attacks = [(c, e) for c in cards for e in c.get("card_text", []) if e["kind"] in ATTACK_KINDS]
dmgs = [damage(e) for _, e in attacks if damage(e)]
stats["card_text"] = {
    "entries": sum(len(c.get("card_text", [])) for c in cards),
    "attacks": len(attacks),
    "attacks_with_damage": len(dmgs),
    "attacks_with_cost": sum(1 for _, e in attacks if e.get("cost")),
    "abilities": sum(1 for c in cards for e in c.get("card_text", []) if e["kind"] in ABILITY_KINDS),
    "damage_median": st.median(dmgs) if dmgs else None,
    "damage_max": max(dmgs) if dmgs else None,
    "cost_size": dict(sorted(collections.Counter(len(e.get("cost", [])) for _, e in attacks).items())),
    "damage_modifier": dict(collections.Counter(re.sub(r"\d+", "", str(e["damage"])) or "fixed"
                                                for _, e in attacks if e.get("damage"))),
}
stats["stage"] = dict(collections.Counter(c.get("stage") or "None" for c in cards).most_common(10))

(ROOT / "eda" / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))

# ================= figures =================
plt.rcParams.update({"font.size": 8, "figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False})
W = 3.3  # ACM single column width in inches

# 1. field completeness
fig, ax = plt.subplots(figsize=(W, 2.6))
items = sorted(((k, 100 - v) for k, v in stats["card_field_missing_pct"].items()
                if k not in {"id", "title", "name", "price_updated"}), key=lambda x: x[1])
ax.barh([k for k, _ in items], [v for _, v in items], color="#3b6ea5")
ax.set_xlabel("% of cards with a non-empty value")
ax.set_xlim(0, 100)
fig.tight_layout(); fig.savefig(FIG / "field_completeness.pdf"); plt.close(fig)

# 2. cards per release year, stacked by category
yrs = sorted(y for y in years if y)
fig, ax = plt.subplots(figsize=(W, 1.9))
bottom = [0] * len(yrs)
for name, color in [("Pokémon", "#3b6ea5"), ("Trainer", "#e0a030"), ("Other/Energy", "#999999")]:
    cnt = collections.Counter(card_year(c) for c in cards if card_category(c) == name)
    vals = [cnt.get(y, 0) for y in yrs]
    ax.bar(yrs, vals, bottom=bottom, color=color, label=name, width=0.8)
    bottom = [b + v for b, v in zip(bottom, vals)]
ax.set_ylabel("cards"); ax.legend(frameon=False, fontsize=7)
fig.tight_layout(); fig.savefig(FIG / "cards_per_year.pdf"); plt.close(fig)

# 3. HP over time (power creep): median HP of Pokémon cards per year
fig, ax = plt.subplots(figsize=(W, 1.8))
byy = collections.defaultdict(list)
for c in cards:
    y = card_year(c)
    if y and c["hp"]:
        byy[y].append(c["hp"])
ys = sorted(byy)
ax.plot(ys, [st.median(byy[y]) for y in ys], marker="o", ms=3, label="median")
ax.plot(ys, [max(byy[y]) for y in ys], marker=".", ms=3, ls="--", label="max")
ax.set_ylabel("HP"); ax.legend(frameon=False, fontsize=7)
fig.tight_layout(); fig.savefig(FIG / "hp_over_time.pdf"); plt.close(fig)

# 4. document length distribution
fig, ax = plt.subplots(figsize=(W, 1.8))
ax.hist([min(x, 400) for x in doc_len], bins=40, color="#3b6ea5")
ax.set_xlabel("words per card document (capped at 400)"); ax.set_ylabel("cards")
fig.tight_layout(); fig.savefig(FIG / "doc_length.pdf"); plt.close(fig)

# 5. price distribution by category (log scale)
fig, ax = plt.subplots(figsize=(W, 1.8))
data = [[c["market_price_max"] for c in cards if c.get("market_price_max") and card_category(c) == k]
        for k in ["Pokémon", "Trainer"]]
ax.boxplot(data, orientation="horizontal", showfliers=False, tick_labels=["Pokémon", "Trainer"])
ax.set_xscale("log"); ax.set_xlabel("max market price (USD, log)")
fig.tight_layout(); fig.savefig(FIG / "price_by_category.pdf"); plt.close(fig)

# 6. top rules-text terms
fig, ax = plt.subplots(figsize=(W, 2.4))
t = stats["top_rules_terms"][:15][::-1]
ax.barh([k for k, _ in t], [v for _, v in t], color="#3b6ea5")
ax.set_xlabel("occurrences in rules text")
fig.tight_layout(); fig.savefig(FIG / "top_terms.pdf"); plt.close(fig)

# 7. attack damage over time
if dmgs:
    fig, ax = plt.subplots(figsize=(W, 1.8))
    byy = collections.defaultdict(list)
    for c, e in attacks:
        y, d = card_year(c), damage(e)
        if y and d:
            byy[y].append(d)
    ys = sorted(byy)
    ax.plot(ys, [st.median(byy[y]) for y in ys], marker="o", ms=3, label="median")
    ax.plot(ys, [sorted(byy[y])[int(0.9 * len(byy[y]))] for y in ys], marker=".", ms=3, ls="--", label="90th pct")
    ax.set_ylabel("attack damage"); ax.legend(frameon=False, fontsize=7)
    fig.tight_layout(); fig.savefig(FIG / "damage_over_time.pdf"); plt.close(fig)

print(json.dumps(stats["card_text"], indent=1, ensure_ascii=False))
print(json.dumps({k: stats[k] for k in ["counts", "category", "doc_words", "mechanics_pct", "price_min_usd",
                                        "vocabulary_size", "cards_with_year", "expansions_with_year",
                                        "rules_text_name_only_pct", "raw_kind_values"]}, indent=1, ensure_ascii=False))
print("top bigrams:", stats["top_rules_bigrams"][:12])
print("top artists:", stats["top_artists"][:6])
print("most expensive:", stats["most_expensive"])
for f in TEXT_FIELDS:
    print(f, stats[f"words_{f}"])
