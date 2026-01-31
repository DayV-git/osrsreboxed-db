"""
Author:  Ashley Thew
Website: https://www.ashleythew.com

Description:
Script to fetch OSRS Wiki shop items from Category:Shops.

Copyright (c) 2025, Ashley Thew

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

import os
import sys
import json
import itertools
import collections
import re
import logging
from pathlib import Path
from datetime import datetime
from datetime import timedelta

import config
from scripts.wiki.wiki_page_titles import WikiPageTitles
from scripts.wiki.wiki_page_text import WikiPageText
from scripts.wiki.wikitext_parser import WikitextIDParser


# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


OSRS_WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
TITLES_FP = Path(config.DATA_SHOPS_PATH / "shops-wiki-page-titles.json")
TEXT_FP = Path(config.DATA_SHOPS_PATH / "shops-wiki-page-text.json")
RG = r" [+-][0-9]{4}"


def fetch():
    """Get all the wiki category page titles and page text."""
    # Try to determine the last update
    if TITLES_FP.exists():
        stream = os.popen(f"git log -1 --format='%ad' {TITLES_FP}")
        last_extraction_date = stream.read().strip()
        last_extraction_date = last_extraction_date.strip("'\"")
        last_extraction_date = re.sub(RG, "", last_extraction_date).strip()
        last_extraction_date = datetime.strptime(
            last_extraction_date, "%a %b %d %H:%M:%S %Y"
        )
        last_extraction_date = last_extraction_date - timedelta(days=3)
    else:
        last_extraction_date = datetime.strptime("2013-02-22", "%Y-%m-%d")

    logger.info("Starting wiki page titles extraction...")
    # Create object to handle page titles extraction
    wiki_page_titles = WikiPageTitles(OSRS_WIKI_API_URL, ["Shops"])

    # Boolean to trigger load page titles from file, or run fresh page title extraction
    load_files = False

    # Load previously extracted page titles from JSON, or extract from OSRS Wiki API
    if load_files:
        loaded_page_titles = wiki_page_titles.load_page_titles(TITLES_FP)
        if not loaded_page_titles:
            logger.error("Specified page titles to load, but not file found. Exiting.")
            sys.exit(1)
    else:
        # Extract page titles using supplied categories
        wiki_page_titles.extract_page_titles()
        # Extract page revision date
        # Loop 50 page titles at a time, the max number for a revisions request using page titles
        for page_title_list in itertools.zip_longest(
            *[iter(wiki_page_titles.page_titles)] * 50
        ):
            # Remove None entries from the list of page titles
            page_title_list = filter(None, page_title_list)
            # Join the page titles list using the pipe (|) separator
            page_titles_string = "|".join(page_title_list)
            # Extract the page revision date
            wiki_page_titles.extract_last_revision_timestamp(page_titles_string)
        # Save all page titles and
        wiki_page_titles.export_page_titles_in_json(TITLES_FP)

    # Determine page titles count
    page_titles_total = len(wiki_page_titles)
    logger.info(f"Number of extracted wiki pages: {page_titles_total}")

    # Open page title JSON file, to check if page needs to have wiki text extracted
    json_data = {}

    if TEXT_FP.exists():
        with open(TEXT_FP, mode="r") as existing_out_file:
            json_data = json.load(existing_out_file)

    page_titles_count = 1
    logger.info("Starting wiki text extraction for extracted page titles...")
    printed_milestones = set()
    for page_title, page_revision_date in wiki_page_titles.page_titles.items():
        # Calculate current progress percentage
        progress_pct = (page_titles_count / page_titles_total) * 100

        # Log only at 25%, 50%, 75%, 100% milestones (once each)
        for milestone in [25, 50, 75, 100]:
            if progress_pct >= milestone and milestone not in printed_milestones:
                printed_milestones.add(milestone)
                logger.info(
                    f"Progress: {page_titles_count:4d} of {page_titles_total:4d} ({progress_pct:.1f}%)"
                )
                break

        # Convert revision date to datetime object
        last_revision_date = datetime.strptime(
            wiki_page_titles[page_title], "%Y-%m-%dT%H:%M:%SZ"
        )

        # Check if page title is already present in JSON output file, also check revision date
        if page_title in json_data and last_revision_date < last_extraction_date:
            # If the last revision was before last extract, skip
            page_titles_count += 1
            continue

        # Create object to extract page wiki text
        wiki_page_text = WikiPageText(OSRS_WIKI_API_URL, page_title)

        # If the page title has not been extracted, extract wiki text and save to JSON file
        wiki_page_text.extract_page_wiki_text()
        wiki_page_text.export_wiki_text_to_json(TEXT_FP)

        page_titles_count += 1


def process():
    logger.info("Starting wiki page text processing...")

    # Load the raw wiki text data
    if not TEXT_FP.exists():
        logger.error("Wiki text file not found. Run fetch() first.")
        return

    with open(TEXT_FP) as f:
        raw_wiki_data = json.load(f)

    # Calculate total shops to process
    total_shops = len(raw_wiki_data)
    logger.info(f"Processing {total_shops} shops...")

    WikiEntry = collections.namedtuple(
        "WikiEntry", "wiki_page_name version_number template_number wikitext"
    )

    export = {}
    shop_count = 0
    printed_milestones = set()

    # Process each shop page, using the page title as the identifier
    for page_title, wikitext in raw_wiki_data.items():
        # Skip pages that are not actual shops (category pages, etc.)
        if any(
            skip in page_title.lower()
            for skip in ["category:", "template:", "user:", "file:"]
        ):
            continue

        # Skip general shop type pages (like "Axe shops", "Magic shops", etc.)
        if (
            page_title.lower().endswith("shops")
            or page_title.lower().endswith("shop")
            and len(page_title.split()) <= 2
        ):
            continue

        # Skip other non-shop pages
        skip_pages = ["Shop", "Unused shops", "General store"]
        if page_title in skip_pages:
            continue

        shop_count += 1

        # Calculate and log progress at 25% intervals (once each)
        progress_pct = (shop_count / total_shops) * 100
        for milestone in [25, 50, 75, 100]:
            if progress_pct >= milestone and milestone not in printed_milestones:
                printed_milestones.add(milestone)
                logger.info(
                    f"Progress: {shop_count:4d} of {total_shops:4d} ({progress_pct:.1f}%)"
                )
                break

        # Check if the page has an infobox shop template
        if "{{Infobox Shop" in wikitext or "{{infobox shop" in wikitext:
            entry = WikiEntry(
                wiki_page_name=page_title,
                version_number="",  # Most shops don't have versions
                template_number=1,  # Default to 1
                wikitext=wikitext,
            )
            # Use the page title as the export key instead of a generated numeric id
            export[page_title] = entry

    logger.info(f"Processed {len(export)} shops with infobox shop templates")

    out_fi = Path(config.DATA_SHOPS_PATH / "shops-wiki-page-text-processed.json")
    with open(out_fi, "w") as f:
        json.dump(export, f, indent=4)


if __name__ == "__main__":
    fetch()
    process()
