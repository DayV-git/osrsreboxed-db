"""Cache NPC and quest transcripts, their references, and NPC identity pages."""

import json
import time

import mwparserfromhell as mw

import config
from scripts.wiki.wiki_page_text import WikiPageText
from scripts.wiki.wiki_page_titles import WikiPageTitles

API = "https://oldschool.runescape.wiki/api.php"
CACHE = config.DATA_PATH / "dialogues" / "wiki-pages.json"
QUEST_CACHE = CACHE.with_name("quest-pages.json")
NPC_CACHE = CACHE.with_name("npc-pages.json")


def save(path, data, *, minified=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    text = json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        **({"separators": (",", ":")} if minified else {"indent": 2}),
    )
    temporary.write_text(text if minified else text + "\n", encoding="utf-8")
    temporary.replace(path)


def read_cache(path):
    return json.loads(path.read_text()) if path.exists() else {}


def transcript_targets(raw):
    return {
        str(link.title).split("#", 1)[0].strip().replace("_", " ")
        for link in mw.parse(raw).filter_wikilinks()
        if str(link.title).strip().startswith("Transcript:")
    }


def participant_pages(raw):
    pages = set()
    for template in mw.parse(raw).filter_templates():
        if str(template.name).strip().casefold() != "transcript list":
            continue
        for param in template.params:
            if not str(param.name).strip().isdigit():
                continue
            value = str(param.value).strip()
            links = mw.parse(value).filter_wikilinks()
            page = (
                str(links[0].title)
                if links
                else value.replace("{{!}}", "|").split("|", 1)[0]
            )
            if page.casefold() not in ("player", "noplayer", ""):
                pages.add(page.strip())
    return sorted(pages)


def download(names, path, session, refresh=False):
    pages = read_cache(path)
    missing = sorted(set(names) if refresh else set(names) - pages.keys())
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
                "redirects": 1,
                "titles": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise ValueError(result["error"])
        query = result["query"]
        fetched = {}
        for page in query["pages"]:
            if "missing" in page or "invalid" in page:
                fetched[page["title"]] = {"missing": True}
                continue
            revision = page["revisions"][0]
            fetched[page["title"]] = {
                "revision": revision["revid"],
                "wikitext": revision["slots"]["main"]["content"],
            }
        aliases = {
            item["from"]: item["to"]
            for kind in ("normalized", "redirects")
            for item in query.get(kind, [])
        }
        for title in batch:
            target, seen = title, set()
            while target in aliases and target not in seen:
                seen.add(target)
                target = aliases[target]
            if target not in fetched:
                raise ValueError(f"Incomplete batch: {title}")
            pages[title] = dict(
                fetched[target], **({"title": target} if target != title else {})
            )
        save(path, pages)
        print(
            f"{path.name}: downloaded {min(offset + 50, len(missing))}/{len(missing)}",
            flush=True,
        )
        time.sleep(0.3)
    return pages


def fetch(refresh=False):
    categories = {}
    for category in ("NPC dialogue", "Quest transcript"):
        titles = WikiPageTitles(API, [category])
        titles.extract_page_titles()
        categories[category] = {
            title for title in titles if title.startswith("Transcript:")
        }
        if not categories[category]:
            raise ValueError(f"{category} returned no transcripts")
    session = WikiPageText(API, "").session
    npc_names = categories["NPC dialogue"]
    pages = download(npc_names, CACHE, session, refresh)
    quests = download(
        categories["Quest transcript"] - npc_names, QUEST_CACHE, session, refresh
    )
    if refresh:
        quests = download(
            set(quests) - categories["Quest transcript"], QUEST_CACHE, session, True
        )
    # Follow explicit dependencies to a fixed point. Cache missing pages too, so a
    # broken wiki link is reported once rather than retried forever.
    while True:
        targets = set().union(
            *(
                transcript_targets(p.get("wikitext", ""))
                for p in [*pages.values(), *quests.values()]
            )
        )
        missing = targets - pages.keys() - quests.keys()
        if not missing:
            break
        quests = download(missing, QUEST_CACHE, session)
    identity_names = {title.removeprefix("Transcript:") for title in npc_names}
    for page in quests.values():
        identity_names.update(participant_pages(page.get("wikitext", "")))
    download(identity_names, NPC_CACHE, session, refresh)
    save(CACHE, {name: pages[name] for name in sorted(npc_names)})
    return {name: pages[name] for name in sorted(npc_names)}


if __name__ == "__main__":
    fetch()
