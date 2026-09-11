"""Download every NPC dialogue category page, caching source separately from gameplay JSON."""

import json
import time

import config
from scripts.wiki.wiki_page_text import WikiPageText
from scripts.wiki.wiki_page_titles import WikiPageTitles

API = "https://oldschool.runescape.wiki/api.php"
CACHE = config.DATA_PATH / "dialogues" / "wiki-pages.json"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def fetch():
    titles = WikiPageTitles(API, ["NPC dialogue"])
    titles.extract_page_titles()
    names = sorted(title for title in titles if title.startswith("Transcript:"))
    if not names:
        raise ValueError("NPC dialogue category returned no transcripts")
    pages = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    missing = [name for name in names if name not in pages]
    print(
        f"Category: {len(names)} transcripts; downloading {len(missing)} uncached pages",
        flush=True,
    )
    session = WikiPageText(API, "").session
    for offset in range(0, len(missing), 50):
        batch = missing[offset : offset + 50]
        response = session.get(
            API,
            headers=config.custom_agent,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "prop": "revisions",
                "rvprop": "ids|content",
                "rvslots": "main",
                "titles": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise ValueError(result["error"])
        fetched = {}
        for page in result["query"]["pages"]:
            revision = page["revisions"][0]
            fetched[page["title"]] = {
                "revision": revision["revid"],
                "wikitext": revision["slots"]["main"]["content"],
            }
        if set(fetched) != set(batch):
            raise ValueError(f"Incomplete batch: {set(batch) - set(fetched)}")
        pages.update(fetched)
        save(CACHE, pages)
        print(f"Downloaded {min(offset + 50, len(missing))}/{len(missing)}", flush=True)
        time.sleep(0.3)
    pages = {name: pages[name] for name in names}
    save(CACHE, pages)
    return pages


if __name__ == "__main__":
    fetch()
