"""Generic helpers for turning MediaWiki wikitext into plain data.

Used by the extraction scripts in this folder.
Requires:  pip install mwparserfromhell
"""
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import mwparserfromhell

# Inline templates that simply display one of their arguments, e.g. {{p|Abra}} -> "Abra".
FIRST_ARGUMENT = {"p", "ct", "g", "m", "a", "t", "e", "rar"}
LAST_ARGUMENT = {"tcgmerch"}  # {{TCGMerch|Scarlet & Violet|Series|151 ex Box}} -> "151 ex Box"

# Templates that carry no prose. They are dropped without being reported as unknown.
IGNORED = {"project tcg notice", "tcggallery"}

# Every template that render() did not know how to handle, with how often it was seen.
# Callers can print this at the end to decide which templates are worth teaching to render().
UNKNOWN_TEMPLATES = Counter()

# Links that should vanish when rendering: categories, files, and other-language links.
_HIDDEN_LINK = re.compile(r"^(category|file|image|media):|^[a-z]{2}(-[a-z]+)?:", re.I)


# ---------- saved card pages ----------
def card_files(data_dir):
    """Every saved card page (data/<set>/<card>.wikitext), skipping the set pages."""
    for path in sorted(Path(data_dir).glob("*/*.wikitext")):
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
    if name == "tcg id" and len(positional) >= 3:  # {{TCG ID|Set|Card|Number}}
        set_name, card_name, number = positional[:3]
        return f"{card_name} ({set_name} {number})"

    # Structural templates that are read separately (infobox, card text, Pokédex data) or ignored.
    if name in IGNORED or "infobox" in name or name.startswith(("cardtext", "carddex", "tcgtrainer")):
        return ""

    UNKNOWN_TEMPLATES[name] += 1
    return ""  # unknown templates are dropped (and counted) rather than guessed


def render(wikitext):
    """Wikitext -> plain text.

    Known inline templates keep their text, links become their label, and tables, comments,
    references, galleries and unknown templates are removed.
    """
    text = str(wikitext)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)  # tables
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