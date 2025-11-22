"""
Author:  PH01L
Email:   phoil@osrsbox.com
Website: https://www.osrsbox.com

Copyright (c) 2019, PH01L

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

import json
import logging
from pathlib import Path
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

LOG = logging.getLogger(__name__)


class WikiPageText:
    """This class handles extraction of wiki text using an OSRS Wiki API query.

    :param base_url: The OSRS Wiki URL used for API queries.
    :param page_title: OSRS Wiki page titles used for API query.
    """

    def __init__(self, base_url: str, page_title: str):
        self.base_url = base_url
        self.page_title = page_title
        self.wiki_text = None
        # Session with retry/backoff that respects Retry-After
        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=0.5,
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def extract_page_wiki_text(self):
        """Extract wiki text from OSRS Wiki for a provided page name.

        This function uses the class attributes as input to query the OSRS Wiki
        API and extract the wiki text for a specific page. The page to query is
        determined by the page title.
        """
        request = {
            "action": "parse",
            "prop": "wikitext",
            "format": "json",
            "page": self.page_title,
        }

        wiki_text: Optional[str] = None

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.get(
                    self.base_url,
                    headers=config.custom_agent,
                    params=request,
                    timeout=15,
                )
            except requests.exceptions.RequestException as e:
                if attempt == max_attempts:
                    raise SystemExit(">>> ERROR: Get request error. Exiting.") from e
                wait = 2 ** attempt
                LOG.warning("RequestException fetching %s (attempt %d/%d): %s — retrying in %ds",
                            self.page_title, attempt, max_attempts, e, wait)
                time.sleep(wait)
                continue

            # Try decode JSON and handle non-JSON (HTML error pages / rate limits)
            try:
                page_data = resp.json()
            except ValueError:
                snippet = resp.text[:300].replace("\n", " ")
                LOG.warning("Non-JSON response for page %s (status=%s). Snippet: %s",
                            self.page_title, resp.status_code, snippet)
                if attempt == max_attempts:
                    LOG.error(">>> ERROR: Non-JSON response from wiki API after retries. Skipping page: %s", self.page_title)
                    page_data = None
                    break
                # Backoff more aggressively on 429
                wait = 2 ** attempt if resp.status_code == 429 else 1
                time.sleep(wait)
                continue

            # Successful JSON -> try to extract wiki text
            if page_data is None:
                wiki_text = None
                break
            try:
                wiki_text = page_data["parse"]["wikitext"]["*"]
            except KeyError:
                wiki_text = None
            break

        self.wiki_text = wiki_text

    def export_wiki_text_to_json(self, out_file_name: str):
        """Export all extracted wiki text to a JSON file.

        Querying the OSRS Wiki constantly is a bad approach. This function writes any
        extracted wiki text to a file to save re-querying the API. This function
        attempts to overwrite pre-existing wiki text entry in a file, where the key
        is the page title, and the value is the wiki text.

        :param out_file_name: The file name to save wiki text to.
        """
        # Create dictionary for export
        json_data = {self.page_title: str(self.wiki_text)}

        out_file_name = Path(out_file_name)

        # Write dictionary to JSON file
        for attempt in range(5):
            try:
                if not out_file_name.exists():
                    with open(str(out_file_name), mode="w") as out_file:
                        out_file.write(json.dumps(json_data, indent=4))
                else:
                    with open(out_file_name) as feeds_json:
                        feeds = json.load(feeds_json)
                    feeds[self.page_title] = str(self.wiki_text)
                    with open(str(out_file_name), mode="w") as out_file:
                        out_file.write(json.dumps(feeds, indent=4))
                break
            except OSError as e:
                if attempt == 4:
                    raise
                print(f"File open failed ({e}), retrying...")
                time.sleep(0.5)
