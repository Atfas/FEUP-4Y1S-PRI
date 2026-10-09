import re
import json
from fetching.helper import BATCH, page_links, chunks, wikitext_batch, log
from fetching.storage import wikitext_path, load_redirects, redirects_path

def build_dataset(out_dir="data", max_expansions=None):
    # step 1: gather a list of all expansions in the tcg
    log("step 1: expansions list")
    expansions = [t for t in page_links("List_of_Pokémon_Trading_Card_Game_expansions") if t.endswith(" (TCG)")]
    expansions = expansions[:max_expansions]
    log(f"  {len(expansions)} expansions to process")

    total_saved = 0
    for i, exp_page in enumerate(expansions, 1):
        # step 2: card list for this expansion
        exp_name = exp_page[: -len(" (TCG)")]
        log(f"\n[{i}/{len(expansions)}] {exp_name}")
        
        pattern = re.compile(rf"^.+ \({re.escape(exp_name)} [^()\s]+\)$")
        links = page_links(exp_page)
        cards = [t for t in links if pattern.match(t)]
        log(f"    {len(cards)} card pages ({len(links) - len(cards)} other links ignored)")
        cards.append(exp_page) # the set page's own wikitext rides along in the batches
        
        # step 3: fetch wikitext at most 50 titles per request, skipping what is already on disk
        redirects = load_redirects(out_dir, exp_name)
        todo = [t for t in cards
                if t not in redirects and not wikitext_path(out_dir, exp_name, t).exists()]
        log(f"    {len(cards) - len(todo)} already on disk or redirected, {len(todo)} to fetch")

        batches = list(chunks(todo, BATCH))
        for n, batch in enumerate(batches, 1):
            pages, moved, missing = wikitext_batch(batch)
            for title, wikitext in pages.items():
                path = wikitext_path(out_dir, exp_name, title)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(wikitext, encoding="utf-8")
            redirects.update(moved)
            redirects_path(out_dir, exp_name).parent.mkdir(parents=True, exist_ok=True)
            redirects_path(out_dir, exp_name).write_text(json.dumps(redirects, indent=2, ensure_ascii=False), encoding="utf-8")
            if missing:
                log(f"    ! missing: {missing[:5]}")
            total_saved += len(pages)
            log(f"    batch {n}/{len(batches)}: asked {len(batch)}, saved {len(pages)}, "
                f"{len(moved)} redirected, {len(missing)} missing")
            log(f"\ndone: {total_saved} pages saved")


if __name__ == "__main__":
    build_dataset()