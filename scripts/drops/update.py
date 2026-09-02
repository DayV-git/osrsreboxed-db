"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Program to generate the OSRS npc drops JSON dump.

Reads the monster wiki page text already fetched by ``scripts.monsters.update``,
parses every ``==Drops==`` table on those pages, and writes the dump to
``docs/drops-json/``. Item and npc IDs come from the databases in this
repository, so the only network access is a single wiki page (``Drop table``)
holding the shared drop tables, which is cached under ``data/drops/``.

Usage:
    python -m scripts.drops.update
    python -m scripts.drops.update --limit 50 --out /tmp/drops

Copyright (c) 2026, Toby Wisener

###############################################################################
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
###############################################################################
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Optional

import config
from builders.run_log import begin_run
from osrsreboxed import items_api
from scripts.drops import drops_tables
from scripts.drops.drops_tables import ItemIdLookup, NpcDropsAggregator
from scripts.drops.drops_wikitext import (
    has_non_numeric_npc_id,
    parse_all_drop_tables,
)
from scripts.wiki.wiki_page_text import WikiPageText

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"

# Alternate encounters (Echo bosses) share npc IDs with their canonical page.
ALTERNATE_ENCOUNTER_MARKER = "(echo)"


def load_npc_cache_names() -> Dict[int, str]:
    """Map npc ID to its cache name, used to tell shared-page variants apart."""
    with open(
        Path(config.DATA_MONSTERS_PATH / "monsters-cache-data.json")
    ) as monsters_file:
        cache_data = json.load(monsters_file)
    return {int(npc_id): monster["name"] for npc_id, monster in cache_data.items()}


def load_monster_wikitext() -> Dict[str, str]:
    """Load the monster wiki page text fetched by ``scripts.monsters.update``."""
    page_text_file = Path(config.DATA_MONSTERS_PATH / "monsters-wiki-page-text.json")
    if not page_text_file.exists():
        raise SystemExit(
            f">>> ERROR: {page_text_file.name} not found. Run scripts.monsters.update first."
        )
    with open(page_text_file) as wiki_file:
        return json.load(wiki_file)


def load_shared_table_wikitext(refresh: bool = False) -> Optional[str]:
    """Load the wikitext of the wiki's ``Drop table`` page, fetching it if needed.

    :param refresh: Re-fetch the page even when a cached copy exists.
    :return: The page wikitext, or None when it could not be fetched.
    """
    config.DATA_DROPS_PATH.mkdir(parents=True, exist_ok=True)
    cache_file = Path(config.DATA_DROPS_PATH / "drop-tables-wiki-page-text.json")

    if cache_file.exists() and not refresh:
        with open(cache_file) as drop_table_file:
            cached = json.load(drop_table_file)
        page_text = cached.get(drops_tables.SHARED_TABLE_PAGE)
        if page_text and page_text != "None":
            return page_text

    logger.info(
        "Fetching '%s' wiki page for shared drop tables...",
        drops_tables.SHARED_TABLE_PAGE,
    )
    page = WikiPageText(WIKI_API_URL, drops_tables.SHARED_TABLE_PAGE)
    page.extract_page_wiki_text()
    if not page.wiki_text:
        logger.warning(
            "Could not fetch '%s' — shared tables will be empty.",
            drops_tables.SHARED_TABLE_PAGE,
        )
        return None
    page.export_wiki_text_to_json(str(cache_file))
    return page.wiki_text


def generate(
    out_dir: Path, limit: Optional[int] = None, refresh_shared: bool = False
) -> None:
    """Parse every monster wiki page and write the drops dump.

    :param out_dir: Directory to write the dump files to.
    :param limit: Stop after this many wiki pages (for quick test runs).
    :param refresh_shared: Re-fetch the shared drop table wiki page.
    """
    logger.info("Loading item database for drop item ID lookup...")
    items = ItemIdLookup(items_api.load())
    npc_names = load_npc_cache_names()
    all_wikitext = load_monster_wikitext()

    aggregator = NpcDropsAggregator(npc_names=npc_names)
    scanned_pages = 0
    skipped_pages = 0

    total_pages = len(all_wikitext) if limit is None else min(limit, len(all_wikitext))
    logger.info("Processing %d monster wiki pages...", total_pages)

    for page_title, page_wikitext in all_wikitext.items():
        if limit is not None and scanned_pages >= limit:
            break
        scanned_pages += 1
        if scanned_pages % 250 == 0:
            logger.info("Progress: %4d of %4d pages", scanned_pages, total_pages)

        if ALTERNATE_ENCOUNTER_MARKER in page_title.lower():
            skipped_pages += 1
            continue
        if not page_wikitext or page_wikitext == "None":
            skipped_pages += 1
            continue
        if has_non_numeric_npc_id(page_wikitext):
            skipped_pages += 1
            continue

        tables = parse_all_drop_tables(page_wikitext)
        if not tables:
            skipped_pages += 1
            continue

        wiki_page = page_title.replace(" ", "_")
        exported = 0
        for table in tables:
            spec = drops_tables.build_table_spec(wiki_page, table, items)
            if not spec.has_drop_content():
                continue
            aggregator.add(spec)
            exported += 1
        if not exported:
            skipped_pages += 1

    subtables = drops_tables.export_shared_subtables(
        load_shared_table_wikitext(refresh=refresh_shared), items
    )
    aggregator.write(out_dir, subtables, scanned_pages)

    logger.info(
        "Wrote drops dump to %s (%d npcs, %d tables, %d pages scanned, %d skipped)",
        out_dir,
        len(aggregator.npcs),
        len(aggregator.tables),
        scanned_pages,
        skipped_pages,
    )
    if aggregator.unresolved_items:
        logger.info(
            "%d drop names could not be matched to an item ID (see unresolved-items.json)",
            len(aggregator.unresolved_items),
        )


def main():
    parser = argparse.ArgumentParser(
        description="Generate the OSRS npc drops JSON dump."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=config.DOCS_DROPS_PATH,
        help="Directory to write the dump files to.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process this many wiki pages."
    )
    parser.add_argument(
        "--refresh-shared",
        action="store_true",
        help="Re-fetch the 'Drop table' wiki page instead of using the cached copy.",
    )
    args = parser.parse_args()

    begin_run("scripts_drops_update")
    logger.info("Starting npc drops extraction...")
    generate(out_dir=args.out, limit=args.limit, refresh_shared=args.refresh_shared)
    logger.info("Npc drops extraction completed!")


if __name__ == "__main__":
    main()
