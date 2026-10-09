from urllib.parse import quote
from pathlib import Path
import json

def safe_name(title):
    """Titles can contain characters that are illegal in filenames (/ : ? *), so encode them."""
    name = quote(title.replace(" ", "_"), safe="()_-.,'!&")
    if name.endswith("."):  # Windows strips trailing dots from file/folder names
        name = name[:-1] + "%2E"
    return name


def wikitext_path(out_dir, exp_name, title):
    return Path(out_dir) / safe_name(exp_name) / (safe_name(title) + ".wikitext")

def redirects_path(out_dir, exp_name):
    return Path(out_dir) / safe_name(exp_name) / "_redirects.json"

def load_redirects(out_dir, exp_name):
    p = redirects_path(out_dir, exp_name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
