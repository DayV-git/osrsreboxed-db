"""
Author:  DayV
Email:   dayv6842@gmail.com

Description:
Shared utility for fetching and processing OSRS Wiki pages for different entity types.
Provides common logic for wiki page extraction and wikitext processing.

Copyright (c) 2026, DayV

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
import re
import collections
import logging
from pathlib import Path
from datetime import datetime
from datetime import timedelta

from scripts.wiki.wiki_page_titles import WikiPageTitles
from scripts.wiki.wiki_page_text import WikiPageText
from scripts.wiki.wikitext_parser import WikitextIDParser


# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


class WikiProperties:
    """Shared utility for wiki property fetching and processing across entity types."""

    OSRS_WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
    REVISION_DATE_REGEX = r" [+-][0-9]{4}"

    def __init__(
        self,
        categories,
        template_names,
        titles_filepath,
        text_filepath,
        processed_filepath,
    ):
        """Initialize WikiProperties with entity-specific configuration.

        Args:
            categories (list): Wiki categories to extract (e.g., ["Items", "Pets"] or ["Monsters"])
            template_names (list): Infobox template names to look for (e.g., ["infobox item", "infobox pet"])
            titles_filepath (Path): Path to save/load wiki page titles JSON
            text_filepath (Path): Path to save/load wiki page text JSON
            processed_filepath (Path): Path to save processed wiki data JSON
        """
        self.categories = categories
        self.template_names = template_names
        self.titles_filepath = titles_filepath
        self.text_filepath = text_filepath
        self.processed_filepath = processed_filepath

    def fetch(self):
        """Get all the wiki category page titles and page text."""
        # Try to determine the last update
        if self.titles_filepath.exists():
            stream = os.popen(f"git log -1 --format='%ad' {self.titles_filepath}")
            last_extraction_date = stream.read().strip()
            last_extraction_date = last_extraction_date.strip("'\"")
            last_extraction_date = re.sub(
                self.REVISION_DATE_REGEX, "", last_extraction_date
            ).strip()
            last_extraction_date = datetime.strptime(
                last_extraction_date, "%a %b %d %H:%M:%S %Y"
            )
            last_extraction_date = last_extraction_date - timedelta(days=3)
        else:
            last_extraction_date = datetime.strptime("2013-02-22", "%Y-%m-%d")

        logger.info(
            f"Starting wiki page titles extraction for categories: {self.categories}..."
        )
        # Create object to handle page titles extraction
        wiki_page_titles = WikiPageTitles(self.OSRS_WIKI_API_URL, self.categories)

        # Boolean to trigger load page titles from file, or run fresh page title extraction
        load_files = False

        # Load previously extracted page titles from JSON, or extract from OSRS Wiki API
        if load_files:
            loaded_page_titles = wiki_page_titles.load_page_titles(self.titles_filepath)
            if not loaded_page_titles:
                logger.error(
                    "Specified page titles to load, but no file found. Exiting."
                )
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
            wiki_page_titles.export_page_titles_in_json(self.titles_filepath)

        # Determine page titles count
        page_titles_total = len(wiki_page_titles)
        logger.info(f"Number of extracted wiki pages: {page_titles_total}")

        # Open page title JSON file, to check if page needs to have wiki text extracted
        json_data = {}

        if self.text_filepath.exists():
            try:
                with open(self.text_filepath, mode="r") as existing_out_file:
                    file_content = existing_out_file.read().strip()
                    if file_content:
                        json_data = json.loads(file_content)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(
                    f"Failed to load existing wiki text file: {e}. Starting fresh."
                )
                json_data = {}

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
            wiki_page_text = WikiPageText(self.OSRS_WIKI_API_URL, page_title)

            # If the page title has not been extracted, extract wiki text and save to JSON file
            wiki_page_text.extract_page_wiki_text()
            wiki_page_text.export_wiki_text_to_json(self.text_filepath)

            page_titles_count += 1

    def process(self):
        """Process wiki page text and extract infobox data."""
        logger.info(
            f"Starting wiki page text processing for templates: {self.template_names}..."
        )

        # Call WikitextIDParser to map:
        # 1. ID to infobox template version
        # 2. ID to wikitext entry
        wiki_data_ids = WikitextIDParser(self.text_filepath, self.template_names)
        wiki_data_ids.process_osrswiki_data_dump()

        # Build the WikiEntry namedtuple based on template type
        # Items have: wiki_page_name, version_number, wikitext
        # Monsters have: wiki_page_name, version_number, template_number, wikitext
        has_template_number = hasattr(wiki_data_ids, "item_id_to_template_number")

        if has_template_number:
            WikiEntry = collections.namedtuple(
                "WikiEntry", "wiki_page_name version_number template_number wikitext"
            )
        else:
            WikiEntry = collections.namedtuple(
                "WikiEntry", "wiki_page_name version_number wikitext"
            )

        # Calculate total items to process
        total_items = len(wiki_data_ids.item_id_to_wikitext)
        logger.info(f"Processing {total_items} items...")

        export = {}
        item_count = 0
        printed_milestones = set()

        for item_id, wikitext in wiki_data_ids.item_id_to_wikitext.items():
            item_count += 1

            # Calculate progress percentage
            progress_pct = (item_count / total_items) * 100

            # Log only at 25%, 50%, 75%, 100% milestones (once each)
            for milestone in [25, 50, 75, 100]:
                if progress_pct >= milestone and milestone not in printed_milestones:
                    printed_milestones.add(milestone)
                    logger.info(
                        f"Progress: {item_count:4d} of {total_items:4d} ({progress_pct:.1f}%)"
                    )
                    break

            if has_template_number:
                entry = WikiEntry(
                    wiki_page_name=wiki_data_ids.item_id_to_wiki_name[item_id],
                    version_number=wiki_data_ids.item_id_to_version_number[item_id],
                    template_number=wiki_data_ids.item_id_to_template_number[item_id],
                    wikitext=wikitext,
                )
            else:
                entry = WikiEntry(
                    wiki_page_name=wiki_data_ids.item_id_to_wiki_name[item_id],
                    version_number=wiki_data_ids.item_id_to_version_number[item_id],
                    wikitext=wikitext,
                )
            export[item_id] = entry

        with open(self.processed_filepath, "w") as f:
            json.dump(export, f, indent=4)
