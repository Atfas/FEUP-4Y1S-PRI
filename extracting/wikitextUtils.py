"""Generic helpers for turning MediaWiki wikitext into plain data.

Used by cards_json.py now, and meant to be reused for the artist and Pokémon pages later.
Requires:  pip install mwparserfromhell
"""
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import mwparserfromhell

# Inline templates that simply display one of their arguments, e.g. {{p|Abra}} -> "Abra".
FIRST_ARGUMENT = {"p", "ct", "g", "m", "a", "t", "e", "rar", "obp", "rf"}
LAST_ARGUMENT = {"tcgmerch"}  # {{TCGMerch|Scarlet & Violet|Series|151 ex Box}} -> "151 ex Box"

# Templates that carry no prose. They are dropped without being reported as unknown.
IGNORED = {"project tcg notice", "tcggallery", "-", "disambig"}

# Unknown templates inside prose usually wrap a word that belongs in the sentence, e.g.
# {{flag|Thailand}} or {{type|Ice}}. When True, an unknown template shows its first positional
# argument instead of leaving a gap. Unknown names are still counted in UNKNOWN_TEMPLATES.
UNKNOWN_TEMPLATE_FALLBACK = True

# Every template that render() did not know how to handle, with how often it was seen.
# Callers can print this at the end to decide which templates are worth teaching to render().
UNKNOWN_TEMPLATES = Counter()

# Links that should vanish when rendering: categories, files, and other-language links.
_HIDDEN_LINK = re.compile(r"^(category|file|image|media):|^[a-z]{2}(-[a-z]+)?:", re.I)


# ---------- saved card pages ----------
# Folders under data/ that hold artist and Pokémon pages, not sets. Folders starting with "_" are
# bookkeeping (e.g. _indexes).
NON_SET_FOLDERS = {"artists", "pokemon"}


def card_files(data_dir):
    """Every saved card page (data/<set>/<card>.wikitext), skipping set, artist and Pokémon pages."""
    for path in sorted(Path(data_dir).glob("*/*.wikitext")):
        folder = path.parent.name
        if folder in NON_SET_FOLDERS or folder.startswith("_"):
            continue
        if not path.name.endswith("_(TCG).wikitext"):
            yield path


def title_of(path):
    """The page title for a saved file, e.g. Abra_(151_63).wikitext -> 'Abra (151 63)'."""
    return unquote(path.name[: -len(".wikitext")]).replace("_", " ")


# ---------- wikitext ----------
def template_name(template):
    """Lower-case template name with underscores turned into spaces."""
    return str(template.name).strip().lower().replace("_", " ")


def _render_template(template):
    name = template_name(template)
    positional = [render(p.value) for p in template.params if not p.showkey]

    if name in FIRST_ARGUMENT:
        return positional[0] if positional else ""
    if name in LAST_ARGUMENT:
        return positional[-1] if positional else ""
    if name == "tcg":
        # {{TCG|Full Art card|Full Art}}: the page is the first argument, the displayed text the second.
        if len(positional) >= 2:
            return positional[1]
        return positional[0] if positional else ""
    if name == "shiny":
        return "Shiny"
    if name == "berries":
        return "Berries"
    if name.startswith("pagesincategory"):  # a live card count the wiki computes; no text to keep
        return ""
    if name == "tcg id" and len(positional) >= 3:  # {{TCG ID|Set|Card|Number}}
        set_name, card_name, number = positional[:3]
        return f"{card_name} ({set_name} {number})"

    # Structural templates that are read separately (infobox, card text, Pokédex data) or ignored.
    if name in IGNORED or "infobox" in name or name.startswith(("cardtext", "carddex", "tcgtrainer")):
        return ""

    UNKNOWN_TEMPLATES[name] += 1
    if UNKNOWN_TEMPLATE_FALLBACK and positional:
        return positional[0]
    return ""


def render(wikitext):
    """Wikitext -> plain text.

    Known inline templates keep their text, links become their label, and tables, comments,
    references, galleries and unknown templates are removed.
    """
    text = str(wikitext)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)  # whole tables
    text = re.sub(r"^\s*(\|\}|\{\|.*|\|-.*)$", "", text, flags=re.M)  # leftover table pieces
    text = re.sub(r"<(ref|gallery)\b.*?</\1\s*>", "", text, flags=re.S | re.I)
    text = re.sub(r"<ref\b[^>]*/>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)

    code = mwparserfromhell.parse(text)
    for template in code.filter_templates(recursive=False):
        code.replace(template, _render_template(template))
    for link in code.filter_wikilinks():
        if _HIDDEN_LINK.match(str(link.title).strip()):
            try:
                code.remove(link)
            except ValueError:
                pass

    plain = code.strip_code(normalize=True, collapse=True)
    return re.sub(r"[ \t]+", " ", plain).strip()


def sections(wikitext):
    """Flat list of (level, heading, body_wikitext). The text before the first heading is level 0."""
    result = []
    code = mwparserfromhell.parse(wikitext)
    for section in code.get_sections(flat=True, include_lead=True, include_headings=True):
        nodes = list(section.nodes)
        if nodes and isinstance(nodes[0], mwparserfromhell.nodes.Heading):
            heading = nodes[0]
            body = "".join(str(node) for node in nodes[1:])
            result.append((heading.level, render(heading.title), body))
        else:
            result.append((0, None, "".join(str(node) for node in nodes)))
    return result


def categories(wikitext):
    """Names of the [[Category:...]] links on the page."""
    names = []
    for link in mwparserfromhell.parse(wikitext).filter_wikilinks():
        title = str(link.title).strip()
        if title.lower().startswith("category:"):
            names.append(title.split(":", 1)[1].strip())
    return names


def lead_text(wikitext):
    """Plain text of the part of the page before the first heading."""
    for level, _heading, body in sections(wikitext):
        if level == 0:
            return render(body)
    return ""


def section_wikitext(wikitext, name):
    """Wikitext of the first section called `name`, including all of its subsections ('' if absent)."""
    parts = []
    found_level = None
    for level, heading, body in sections(wikitext):
        if found_level is None:
            if level > 0 and heading.lower() == name.lower():
                found_level = level
                parts.append(body)
        elif level <= found_level:
            break
        else:
            parts.append(body)
    return "\n".join(parts)


def read_blocks(wikitext, section_name):
    """Text of a top-level section as a list of {"heading", "text"} blocks.

    The section's own text has heading None; each subsection (===Origin===) is its own block.
    A subsection called Gallery is skipped.
    """
    blocks = []
    inside = False
    for level, heading, body in sections(wikitext):
        if level == 0:
            continue
        if level == 2:
            inside = heading.lower() == section_name
        if not inside:
            continue
        if level > 2 and heading.lower() == "gallery":
            continue
        text = render(body)
        if text:
            blocks.append({"heading": heading if level > 2 else None, "text": text})
    return blocks


# ---------- disambiguation pages ----------
def is_disambiguation(wikitext):
    return "{{disambig" in wikitext.lower()


def disambiguation_target(wikitext):
    """On a disambiguation page, the title of the TCG illustrator's page (or None).

    Looks for the list item that mentions {{PTCG}} or "illustrator" and takes its first link,
    for example the line:  * For the {{PTCG}} illustrator, see [[akagi (illustrator)]].
    """
    if not is_disambiguation(wikitext):
        return None
    for line in wikitext.splitlines():
        lowered = line.lower()
        if "{{ptcg}}" in lowered or "illustrator" in lowered:
            match = re.search(r"\[\[([^\]|#]+)", line)
            if match:
                title = match.group(1).strip().replace("_", " ")
                return title[:1].upper() + title[1:]  # the wiki ignores the first letter's case
    return None


def drop_count_sentences(wikitext):
    """Remove sentences that only report a live card count or point at a category page.

    Artist pages say things like "Aimi has illustrated {{PAGESINCATEGORY:Illus. by Aimi}} cards."
    and "A full list of cards can be found [[:Category:Illus. by Aimi|here]]." The wiki fills in
    the number itself, so the wikitext has nothing to keep, and rendering would leave a gap
    ("has illustrated cards"). Call this on artist wikitext before rendering it.
    """
    lines = []
    for line in wikitext.splitlines():
        lowered = line.lower()
        if "pagesincategory" in lowered or "[[:category:" in lowered:
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z'\"\[{])", line)
            kept = [
                s for s in sentences
                if "pagesincategory" not in s.lower() and "[[:category:" not in s.lower()
            ]
            line = " ".join(kept)
        lines.append(line)
    return "\n".join(lines)