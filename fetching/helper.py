import re
import requests
import time

API = "https://bulbapedia.bulbagarden.net/w/api.php"
HEADERS = {"User-Agent": "Academic_Information_Project/0.1 (up202304387@g.uporto.pt)"}
DELAY = 2.0
BATCH = 50 # max number of titles per API request

VERBOSE = True  # set to False to suppress progress messages

def log(*args):
    if VERBOSE:
        print(*args, flush=True)

def api_get(**params):
    """One place for URL, headers, default params and error checks."""
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    params.setdefault("maxlag", 5)
    for attempt in range(6):
        r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                wait = int(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 5 * 2 ** attempt  # 5, 10, 20, 40, 80, 160s
            print(f"    HTTP {r.status_code}, waiting {wait}s (attempt {attempt + 1}/6)", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("error", {}).get("code") == "maxlag":
            time.sleep(5)
            continue
        time.sleep(DELAY)
        return data
    raise RuntimeError(f"API kept failing for {params}")


def page_links(title):
    """Titles of all main-namespace links on a page."""
    data = api_get(action="parse", page=title, prop="links")
    if(data.get("error", {}).get("code") == "missingtitle"):
        log(f"    {title}: page missing")
        return []
    links = [l["title"] for l in data["parse"]["links"] if l["ns"] == 0]
    log(f"    {title}: {len(links)} links")
    return links


def chunks(items, n):
    """ gradually yield successive n-sized chunks from items."""
    for i in range(0, len(items), n):
        yield items[i : i + n]


def wikitext_batch(titles):
    """Up to 50 titles in one call. Missing pages are skipped."""
    data = api_get(action="query", titles="|".join(titles), prop="revisions", rvprop="content", rvslots="main", redirects=1)
    q = data["query"]
    norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
    redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
    pages = {p["title"]: p["revisions"][0]["slots"]["main"]["content"] for p in q["pages"] if "revisions" in p}
    missing = [p["title"] for p in q["pages"] if "revisions" not in p]
    moved = {}
    for t in titles:
        final = redir.get(norm.get(t, t), norm.get(t, t))
        if final != t:
            moved[t] = final
    return pages, moved, missing

