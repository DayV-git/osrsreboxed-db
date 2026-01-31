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

import re
import json
from pathlib import Path
from collections import defaultdict
import logging

import config
from osrsreboxed import items_api
from scripts.wiki.wikitext_parser import WikitextTemplateParser


# Constants
CURRENCY_NAMES = ["coins", "trading sticks", "tokkul", "pizazz points", "reward points"]

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load items for ID lookup
ITEMS = [item for item in items_api.load() if not item.duplicate and not item.stacked]
# Build lookup dicts for performance
ITEMS_BY_WIKI_NAME = {item.wiki_name: item.id for item in ITEMS if item.wiki_name}
ITEMS_BY_NAME = {item.name: item.id for item in ITEMS}
ITEMS_BY_NAME_LOWER = {item.name.lower(): item.id for item in ITEMS}
ITEMS_BY_WIKI_NAME_LOWER = {
    item.wiki_name.lower(): item.id for item in ITEMS if item.wiki_name
}


def fetch() -> None:
    """Fetch shop items by parsing StoreLine templates from shop pages.

    This method parses the wikitext of shop pages to extract StoreLine templates
    which contain the shop stock information, as well as StoreTableHead templates
    which contain shop buy/sell information. Handles tabber structures for shops
    with multiple substores based on quest completion.
    """
    # Load the shop wikitext file of processed data
    shop_text_file = Path(
        config.DATA_SHOPS_PATH / "shops-wiki-page-text-processed.json"
    )

    if not shop_text_file.exists():
        logger.error(
            "shops-wiki-page-text-processed.json not found. Run shops_properties.py first."
        )
        return

    with open(shop_text_file) as f:
        all_wikitext_processed = json.load(f)

    logger.info(f"Processing {len(all_wikitext_processed)} shop pages...")

    # Data structure for storing complete shop data
    all_shops_data = {}
    shop_count = 0
    total_shops = len(all_wikitext_processed)
    printed_milestones = set()

    for shop_key, shop_data in all_wikitext_processed.items():
        shop_count += 1

        # Calculate and print progress at 25% intervals (once each)
        progress_pct = (shop_count / total_shops) * 100
        for milestone in [25, 50, 75, 100]:
            if progress_pct >= milestone and milestone not in printed_milestones:
                printed_milestones.add(milestone)
                logger.info(
                    f"Progress: {shop_count:4d} of {total_shops:4d} ({progress_pct:.1f}%)"
                )
                break

        # shop_data is a WikiEntry namedtuple stored by `shops_properties.process`
        # where the export key is the page title. Use the page title as shop name.
        shop_name = shop_key
        wikitext = (
            shop_data.wikitext if hasattr(shop_data, "wikitext") else shop_data[3]
        )

        # Check if this shop has tabber structure
        tabber_sections = parse_tabber_structure(wikitext)

        if tabber_sections:
            for section_name, section_content in tabber_sections.items():
                substore_name = f"{shop_name} ({section_name})"
                shop_info = parse_shop_info(section_content)
                shop_items = parse_shop_items(substore_name, section_content)
                if shop_items or any(shop_info.values()):
                    all_shops_data[substore_name] = {
                        "shop_info": shop_info,
                        "items": shop_items,
                    }
                    logger.debug(
                        f"Substore '{section_name}': {len(shop_items)} items, info: {shop_info}"
                    )
        else:
            shop_info = parse_shop_info(wikitext)
            shop_items = parse_shop_items(shop_name, wikitext)
            if shop_items or any(shop_info.values()):
                all_shops_data[shop_name] = {
                    "shop_info": shop_info,
                    "items": shop_items,
                }
                logger.debug(
                    f"Found {len(shop_items)} items and shop info: {shop_info}"
                )
            else:
                logger.info(f"No items or shop info found")

    # Export the results
    out_fi = Path(config.DATA_SHOPS_PATH / "shops-raw.json")
    with open(out_fi, "w") as f:
        json.dump(all_shops_data, f, indent=4)

    logger.info(f"Exported raw shop data.")


def parse_tabber_structure(wikitext: str) -> dict:
    """Parse tabber structure from wikitext to extract substores.

    :param wikitext: The wikitext content of the shop page
    :return: Dictionary mapping tab names to their content, or empty dict if no tabber
    """
    tabber_sections = {}

    # Check for tabber structure
    if "<tabber>" not in wikitext.lower() and "{{tabber" not in wikitext.lower():
        return tabber_sections

    lines = wikitext.split("\n")
    tabber_count = 0
    in_tabber = False
    current_tab = None
    current_content = []

    for line in lines:
        line_lower = line.lower()

        # Check for tabber start
        if "<tabber>" in line_lower or "{{tabber" in line_lower:
            in_tabber = True
            tabber_count += 1
            continue

        # Check for tabber end
        elif "</tabber>" in line_lower or (in_tabber and line.strip() == "}}"):
            in_tabber = False
            # Save the last tab if we have one
            if current_tab and current_content:
                # Add tabber identifier based on position
                tab_name = current_tab
                tabber_sections[tab_name] = "\n".join(current_content)
            current_tab = None
            current_content = []
            continue

        # If we're in a tabber, parse tabs and content
        elif in_tabber:
            # Check if this is a tab definition (contains = and not a template parameter)
            if (
                "=" in line
                and not line.startswith("|")
                and not line.startswith("{{")
                and not line.strip().startswith("*")
            ):

                # Save previous tab if we have one
                if current_tab and current_content:
                    # Add tabber identifier based on position
                    tab_name = current_tab

                    tabber_sections[tab_name] = "\n".join(current_content)

                # Start new tab
                tab_name = line.split("=")[0].strip()
                # Clean up tab name (remove any formatting)
                if len(tab_name) < 50 and "{" not in tab_name:
                    current_tab = tab_name
                    current_content = []
                    # Add the content after the = sign
                    remaining_content = "=".join(line.split("=")[1:]).strip()
                    if remaining_content:
                        current_content.append(remaining_content)
            else:
                # Add to current tab content
                if current_tab is not None:
                    current_content.append(line)

    # Handle case where tabber doesn't close properly
    if current_tab and current_content:
        # Add tabber identifier based on position
        tab_name = current_tab

        tabber_sections[tab_name] = "\n".join(current_content)

    return tabber_sections


def parse_shop_info(wikitext: str) -> dict:
    """Parse shop information from StoreTableHead template.

    :param wikitext: The wikitext content of the shop page
    :return: Dictionary containing shop information including currency
    """
    shop_info = {
        "sells_at": None,
        "buys_at": None,
        "change_per": None,
        "currency": "coins",  # Default to coins
    }

    # Look for StoreTableHead template
    pattern = r"\{\{StoreTableHead\|([^}]+)\}\}"
    matches = re.findall(pattern, wikitext, re.IGNORECASE)

    if matches:
        params_str = matches[0]

        # Parse parameters
        parts = params_str.split("|")
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "sellmultiplier" and value.isdigit():
                    shop_info["sells_at"] = int(value)
                elif key == "buymultiplier" and value.isdigit():
                    shop_info["buys_at"] = int(value)
                elif key == "delta" and value.isdigit():
                    shop_info["change_per"] = int(value)
                elif key == "currency":
                    shop_info["currency"] = value

    return shop_info


def parse_shop_items(shop_name: str, wikitext: str) -> list:
    """Parse StoreLine and Tzhaar shop row templates from shop wikitext to extract items.

    :param shop_name: Name of the shop
    :param wikitext: The wikitext content of the shop page
    :return: List of items sold in the shop
    """
    items = []

    # Extract the section between StoreTableHead and StoreTableBottom
    head_match = re.search(r"\{\{StoreTableHead\|[^}]+\}\}", wikitext, re.IGNORECASE)
    bottom_match = re.search(r"\{\{StoreTableBottom\}\}", wikitext, re.IGNORECASE)

    if not head_match or not bottom_match:
        logger.warning(f"No StoreTableHead or StoreTableBottom found in {shop_name}")
        with open(".error.txt", "a", encoding="utf-8") as errfile:
            print(
                f"WARNING: No StoreTableHead or StoreTableBottom found in {shop_name}",
                file=errfile,
            )
        return items

    section = wikitext[head_match.end() : bottom_match.start()]

    # Find all templates in this section robustly (including nested/multiline)
    # This regex matches {{TemplateName|...}} blocks, including nested braces
    def extract_templates(text):
        templates = []
        i = 0
        while i < len(text):
            if text[i : i + 2] == "{{":
                start = i
                i += 2
                depth = 2
                while i < len(text) and depth > 0:
                    if text[i : i + 2] == "{{":
                        depth += 2
                        i += 2
                    elif text[i : i + 2] == "}}":
                        depth -= 2
                        i += 2
                    else:
                        i += 1
                end = i
                block = text[start:end]
                # Only process if it looks like a template
                if block.startswith("{{") and "|" in block:
                    # Remove outer braces
                    block_inner = block[2:-2]
                    if "|" in block_inner:
                        name, params = block_inner.split("|", 1)
                        templates.append((name.strip(), params.strip()))
            else:
                i += 1
        return templates

    templates = extract_templates(section)

    # First extract currency from StoreTableHead if available

    shop_info = parse_shop_info(wikitext)
    shop_currency = shop_info.get("currency")
    if not shop_currency:
        shop_currency = "coins"

    # Detect shop currency from shop name/wikitext (fallback method)
    if shop_currency == "coins":
        wikitext_lower = wikitext.lower()
        for currency in CURRENCY_NAMES:
            if currency != "coins" and currency in wikitext_lower:
                shop_currency = currency
                break

    # Process all templates in the section

    for template_name, params_str in templates:
        item_data = parse_storeline_params(params_str)
        if item_data and "name" in item_data and item_data["name"]:
            item_id = item_id_lookup(item_data["name"])
            if item_id is not None:
                stock = item_data.get("stock")
                if stock is not None:
                    stock_str = str(stock).strip()
                    if stock_str.lower() in ["inf", "∞", "infinite"]:
                        stock = "infinite"
                    elif stock_str.isdigit():
                        stock = int(stock_str)
                    else:
                        stock = stock_str
                else:
                    stock = None

                restock_time = item_data.get("restock")
                if restock_time is not None and str(restock_time).isdigit():
                    restock_time = int(restock_time)

                currency = item_data.get("currency")
                if not currency:
                    currency = shop_currency if shop_currency else "coins"

                item_info = {
                    "type": "item",
                    "id": item_id,
                    "name": item_data["name"],
                    "shop_name": shop_name,
                    "stock": stock,
                    "restock_time": restock_time,
                    "currency": currency,
                }
                items.append(item_info)
            else:
                logger.warning(f"Could not find item ID for: {item_data['name']}")
                with open(".error.txt", "a", encoding="utf-8") as errfile:
                    print(
                        f"WARNING: Could not find item ID for: {item_data['name']} in shop {shop_name}",
                        file=errfile,
                    )
                unknown_info = {
                    "type": "unknown",
                    "template_name": template_name,
                    "params": params_str,
                    "reason": "No item ID found",
                }
                # Add all parsed parameters to the unknown_info
                unknown_info.update(item_data)
                # Normalize stock field for unknowns
                stock = unknown_info.get("stock")
                if stock is not None:
                    stock_str = str(stock).strip()
                    if stock_str.lower() in ["inf", "∞", "infinite"]:
                        unknown_info["stock"] = "infinite"
                    elif stock_str.isdigit():
                        unknown_info["stock"] = int(stock_str)
                    else:
                        unknown_info["stock"] = stock_str
                items.append(unknown_info)
        else:
            logger.warning(
                f"No valid item name found in {template_name}: {params_str} {item_data}"
            )
            with open(".error.txt", "a", encoding="utf-8") as errfile:
                print(
                    f"WARNING: No valid item name found in {template_name} from {shop_name}",
                    file=errfile,
                )
                print(f"  Params: {params_str}", file=errfile)
            unknown_info = {
                "type": "unknown",
                "template_name": template_name,
                "params": params_str,
                "reason": "No valid item name",
            }
            # Add all parsed parameters to the unknown_info
            unknown_info.update(item_data)
            # Normalize stock field for unknowns
            stock = unknown_info.get("stock")
            if stock is not None:
                stock_str = str(stock).strip()
                if stock_str.lower() in ["inf", "∞", "infinite"]:
                    unknown_info["stock"] = "infinite"
                elif stock_str.isdigit():
                    unknown_info["stock"] = int(stock_str)
                else:
                    unknown_info["stock"] = stock_str
            items.append(unknown_info)

    return items


def parse_storeline_params(params_str: str) -> dict:
    """Parse the parameters of a StoreLine template.

    :param params_str: The parameter string from the StoreLine template
    :return: Dictionary of parsed parameters
    """
    params = {}

    # Split parameters by pipe, but be careful of nested templates
    parts = []
    current_part = ""
    brace_count = 0

    for char in params_str:
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        elif char == "|" and brace_count == 0:
            parts.append(current_part.strip())
            current_part = ""
            continue

        current_part += char

    if current_part.strip():
        parts.append(current_part.strip())

    # Parse each parameter
    for i, part in enumerate(parts):
        if "=" in part:
            key, value = part.split("=", 1)
            key_lower = key.strip().lower()
            params[key_lower] = value.strip()
        else:
            # First parameter without = is usually the name
            if i == 0 and not any(k in params for k in ["name", "Name"]):
                params["name"] = part.strip()

    # Fallback: extract name=... from raw params_str if still missing
    if "name" not in params:
        match = re.search(r"name\s*=\s*([^|}]+)", params_str, re.IGNORECASE)
        if match:
            params["name"] = match.group(1).strip()

    return params


def item_id_lookup(name: str):
    """Look up item ID by name using fast dicts."""
    if not name:
        return None
    name = name.strip()
    # Try exact wiki name match
    if name in ITEMS_BY_WIKI_NAME:
        return ITEMS_BY_WIKI_NAME[name]
    # Try exact name match
    if name in ITEMS_BY_NAME:
        return ITEMS_BY_NAME[name]
    # Try case-insensitive match
    name_lower = name.lower()
    if name_lower in ITEMS_BY_NAME_LOWER:
        return ITEMS_BY_NAME_LOWER[name_lower]
    if name_lower in ITEMS_BY_WIKI_NAME_LOWER:
        return ITEMS_BY_WIKI_NAME_LOWER[name_lower]
    for item_name_lower in ITEMS_BY_NAME_LOWER:
        if item_name_lower.startswith(name_lower):
            return ITEMS_BY_NAME_LOWER[item_name_lower]
    for wiki_name_lower in ITEMS_BY_WIKI_NAME_LOWER:
        if wiki_name_lower.startswith(name_lower):
            return ITEMS_BY_WIKI_NAME_LOWER[wiki_name_lower]
    return None


def process() -> None:
    """Process the raw shop data into a more structured format."""
    # Load the raw shop data
    raw_file = Path(config.DATA_SHOPS_PATH / "shops-raw.json")

    if not raw_file.exists():
        logger.error("shops-items-raw.json not found. Run fetch() first.")
        with open(".error.txt", "a", encoding="utf-8") as errfile:
            print(
                "ERROR: shops-items-raw.json not found. Run fetch() first.",
                file=errfile,
            )
        return

    with open(raw_file) as f:
        raw_shop_data = json.load(f)

    logger.info("Processing raw shop data...")

    # Structure the data - maintain new format with shop info
    shops_by_shop = {}
    shops_by_item = defaultdict(list)

    total_items = 0
    shops_with_info = 0

    for shop_name, shop_data in raw_shop_data.items():
        shop_info = shop_data.get("shop_info", {})
        items = shop_data.get("items", [])

        # Only include items with type 'item' in shops_by_shop
        filtered_items = [item for item in items if item.get("type") == "item"]
        shops_by_shop[shop_name] = {"shop_info": shop_info, "items": filtered_items}

        # Track stats
        if any(shop_info.values()):
            shops_with_info += 1

        # Build items-by-item index
        for item in filtered_items:
            if "id" in item:
                shops_by_item[item["id"]].append(
                    {
                        "shop_name": shop_name,
                        "stock": item.get("stock"),
                        "restock_time": item.get("restock_time"),
                        "currency": item.get("currency", "coins"),
                    }
                )
                total_items += 1

    logger.info(
        f"Processed {len(raw_shop_data)} shops: {total_items} total items, {len(shops_by_item)} unique items"
    )

    # Export both structures
    shops_file = Path(config.DATA_SHOPS_PATH / "shops-items-by-shop.json")
    with open(shops_file, "w") as f:
        json.dump(shops_by_shop, f, indent=4)

    items_file = Path(config.DATA_SHOPS_PATH / "shops-items-by-item.json")
    with open(items_file, "w") as f:
        json.dump(dict(shops_by_item), f, indent=4)

    logger.info(f"Exported processed shop data.")


if __name__ == "__main__":
    fetch()
    process()
