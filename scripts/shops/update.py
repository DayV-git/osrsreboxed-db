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

import logging

from builders.run_log import begin_run
from scripts.shops import shops_properties
from scripts.shops import shop_owners
from scripts.shops import shops_items

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    begin_run("scripts_shops_update")
    logger.info("Starting shop data extraction...")

    logger.info("Step 1: Fetching shop properties from wiki...")
    shops_properties.fetch()
    shops_properties.process()

    logger.info("Step 2: Resolving shop owners to NPC IDs...")
    shop_owners.fetch()
    shop_owners.process()

    logger.info("Step 3: Extracting shop items...")
    shops_items.fetch()
    shops_items.process()

    logger.info("Shop data extraction completed!")


if __name__ == "__main__":
    main()
