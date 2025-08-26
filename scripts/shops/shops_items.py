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
import collections

import config
from osrsreboxed import items_api
from scripts.wiki.wikitext_parser import WikitextTemplateParser


# Load items for ID lookup
ITEMS = [item for item in items_api.load() if not item.duplicate and not item.stacked]


def fetch():
    """Fetch shop items by parsing StoreLine templates from shop pages.

    This method parses the wikitext of shop pages to extract StoreLine templates
    which contain the shop stock information, as well as StoreTableHead templates
    which contain shop buy/sell information. Handles tabber structures for shops
    with multiple substores based on quest completion.
    """
    # Load the shop wikitext file of processed data
    shop_text_file = Path(config.DATA_SHOPS_PATH / "shops-wiki-page-text-processed.json")
    if not shop_text_file.exists():
        print(">>> ERROR: shops-wiki-page-text-processed.json not found. Run shops_properties.py first.")
        return

    with open(shop_text_file) as f:
        all_wikitext_processed = json.load(f)

    print(f">>> Processing {len(all_wikitext_processed)} shop pages...")

    # Data structure for storing complete shop data
    all_shops_data = {}

    for shop_id, shop_data in all_wikitext_processed.items():
        shop_name = shop_data[0]
        wikitext = shop_data[3]

        print(f"  > Processing shop: {shop_name}")

        # Check if this shop has tabber structure
        tabber_sections = parse_tabber_structure(wikitext)

        if tabber_sections:
            # Process each tab as a separate substore
            print(f"    Found tabber with {len(tabber_sections)} sections")
            for section_name, section_content in tabber_sections.items():
                substore_name = f"{shop_name} ({section_name})"

                # Parse shop information and items for this section
                shop_info = parse_shop_info(section_content)
                shop_items = parse_shop_items(substore_name, section_content)

                if shop_items or any(shop_info.values()):
                    all_shops_data[substore_name] = {
                        'shop_info': shop_info,
                        'items': shop_items
                    }
                    print(f"      Substore '{section_name}': {len(shop_items)} items, info: {shop_info}")
        else:
            # Process as normal single shop
            shop_info = parse_shop_info(wikitext)
            shop_items = parse_shop_items(shop_name, wikitext)

            if shop_items or any(shop_info.values()):  # Include if has items OR shop info
                all_shops_data[shop_name] = {
                    'shop_info': shop_info,
                    'items': shop_items
                }
                print(f"    Found {len(shop_items)} items and shop info: {shop_info}")
            else:
                print(f"    No items or shop info found")

    # Export the results
    out_fi = Path(config.DATA_SHOPS_PATH / "shops-items-raw.json")
    with open(out_fi, 'w') as f:
        json.dump(all_shops_data, f, indent=4)

    print(f">>> Exported shop data to {out_fi}")


def parse_tabber_structure(wikitext: str) -> dict:
    """Parse tabber structure from wikitext to extract substores.

    :param wikitext: The wikitext content of the shop page
    :return: Dictionary mapping tab names to their content, or empty dict if no tabber
    """
    tabber_sections = {}

    # Check for tabber structure
    if '<tabber>' not in wikitext.lower() and '{{tabber' not in wikitext.lower():
        return tabber_sections

    lines = wikitext.split('\n')
    tabber_count = 0
    in_tabber = False
    current_tab = None
    current_content = []

    for line in lines:
        line_lower = line.lower()

        # Check for tabber start
        if '<tabber>' in line_lower or '{{tabber' in line_lower:
            in_tabber = True
            tabber_count += 1
            continue

        # Check for tabber end
        elif ('</tabber>' in line_lower or
              (in_tabber and line.strip() == '}}')):
            in_tabber = False
            # Save the last tab if we have one
            if current_tab and current_content:
                # Add tabber identifier based on position
                tab_name = current_tab
                if tabber_count == 1:
                    tab_name = f"{current_tab} (Food)"
                elif tabber_count == 2:
                    tab_name = f"{current_tab} (Items)"

                tabber_sections[tab_name] = '\n'.join(current_content)
            current_tab = None
            current_content = []
            continue

        # If we're in a tabber, parse tabs and content
        elif in_tabber:
            # Check if this is a tab definition (contains = and not a template parameter)
            if ('=' in line and
                not line.startswith('|') and
                not line.startswith('{{') and
                    not line.strip().startswith('*')):

                # Save previous tab if we have one
                if current_tab and current_content:
                    # Add tabber identifier based on position
                    tab_name = current_tab
                    if tabber_count == 1:
                        tab_name = f"{current_tab} (Food)"
                    elif tabber_count == 2:
                        tab_name = f"{current_tab} (Items)"

                    tabber_sections[tab_name] = '\n'.join(current_content)

                # Start new tab
                tab_name = line.split('=')[0].strip()
                # Clean up tab name (remove any formatting)
                if len(tab_name) < 50 and '{' not in tab_name:
                    current_tab = tab_name
                    current_content = []
                    # Add the content after the = sign
                    remaining_content = '='.join(line.split('=')[1:]).strip()
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
        if tabber_count == 1:
            tab_name = f"{current_tab} (Food)"
        elif tabber_count == 2:
            tab_name = f"{current_tab} (Items)"

        tabber_sections[tab_name] = '\n'.join(current_content)

    return tabber_sections


def parse_shop_info(wikitext: str) -> dict:
    """Parse shop information from StoreTableHead template.

    :param wikitext: The wikitext content of the shop page
    :return: Dictionary containing shop information
    """
    shop_info = {
        'sells_at': None,
        'buys_at': None,
        'change_per': None
    }

    # Look for StoreTableHead template
    pattern = r'\{\{StoreTableHead\|([^}]+)\}\}'
    matches = re.findall(pattern, wikitext, re.IGNORECASE)

    if matches:
        params_str = matches[0]

        # Parse parameters
        parts = params_str.split('|')
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                key = key.strip().lower()
                value = value.strip()

                if key == 'sellmultiplier' and value.isdigit():
                    shop_info['sells_at'] = int(value)
                elif key == 'buymultiplier' and value.isdigit():
                    shop_info['buys_at'] = int(value)
                elif key == 'delta' and value.isdigit():
                    shop_info['change_per'] = int(value)

    return shop_info


def parse_shop_items(shop_name: str, wikitext: str) -> list:
    """Parse StoreLine templates from shop wikitext to extract items.

    :param shop_name: Name of the shop
    :param wikitext: The wikitext content of the shop page
    :return: List of items sold in the shop
    """
    items = []

    # Find all StoreLine templates
    storeline_pattern = r'\{\{StoreLine\|([^}]+)\}\}'
    matches = re.findall(storeline_pattern, wikitext, re.IGNORECASE)

    for match in matches:
        # Parse the parameters of the StoreLine template
        item_data = parse_storeline_params(match)
        if item_data and 'name' in item_data and item_data['name']:
            # Look up item ID
            item_id, is_members = item_id_lookup(item_data['name'])
            if item_id is not None:
                item_info = {
                    'id': item_id,
                    'name': item_data['name'],
                    'shop_name': shop_name,
                    'stock': item_data.get('stock'),
                    'restock_time': item_data.get('restock'),
                    'members': is_members,
                    'price': item_data.get('price'),
                    'currency': item_data.get('currency', 'coins')
                }
                items.append(item_info)
            else:
                print(f"    WARNING: Could not find item ID for: {item_data['name']}")
        else:
            print(f"    WARNING: No valid item name found in StoreLine: {match[:50]}...")

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
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
        elif char == '|' and brace_count == 0:
            parts.append(current_part.strip())
            current_part = ""
            continue

        current_part += char

    if current_part.strip():
        parts.append(current_part.strip())

    # Parse each parameter
    for i, part in enumerate(parts):
        if '=' in part:
            key, value = part.split('=', 1)
            params[key.strip()] = value.strip()
        else:
            # First parameter without = is usually the name
            if i == 0 and 'name' not in params:
                params['name'] = part.strip()

    return params


def item_id_lookup(name: str) -> tuple:
    """Look up item ID by name.

    :param name: Item name to look up
    :return: Tuple of (item_id, is_members) or (None, None) if not found
    """
    if not name:
        return None, None

    # Clean up the name
    name = name.strip()

    # Try exact wiki name match first
    for item in ITEMS:
        if item.wiki_name == name:
            return item.id, item.members

    # Try exact name match
    for item in ITEMS:
        if item.name == name:
            return item.id, item.members

    # Try case-insensitive match
    name_lower = name.lower()
    for item in ITEMS:
        if item.name.lower() == name_lower:
            return item.id, item.members

    # Try wiki name case-insensitive match
    for item in ITEMS:
        if item.wiki_name and item.wiki_name.lower() == name_lower:
            return item.id, item.members

    return None, None


def process():
    """Process the raw shop data into a more structured format."""
    # Load the raw shop data
    raw_file = Path(config.DATA_SHOPS_PATH / "shops-items-raw.json")
    if not raw_file.exists():
        print(">>> ERROR: shops-items-raw.json not found. Run fetch() first.")
        return

    with open(raw_file) as f:
        raw_shop_data = json.load(f)

    print(">>> Processing raw shop data...")

    # Structure the data - maintain new format with shop info
    shops_by_shop = {}
    shops_by_item = defaultdict(list)

    total_items = 0
    shops_with_info = 0

    for shop_name, shop_data in raw_shop_data.items():
        shop_info = shop_data.get('shop_info', {})
        items = shop_data.get('items', [])

        # Keep the new structure with shop info
        shops_by_shop[shop_name] = {
            'shop_info': shop_info,
            'items': items
        }

        # Track stats
        if any(shop_info.values()):
            shops_with_info += 1

        # Build items-by-item index
        for item in items:
            shops_by_item[item['id']].append({
                'shop_name': shop_name,
                'stock': item.get('stock'),
                'restock_time': item.get('restock_time'),
                'price': item.get('price'),
                'currency': item.get('currency', 'coins')
            })
            total_items += 1

    print(f">>> Processed {len(raw_shop_data)} shops:")
    print(f"    - {shops_with_info} shops with buy/sell info")
    print(f"    - {total_items} total items")
    print(f"    - {len(shops_by_item)} unique items sold across all shops")

    # Export both structures
    shops_file = Path(config.DATA_SHOPS_PATH / "shops-items-by-shop.json")
    with open(shops_file, 'w') as f:
        json.dump(shops_by_shop, f, indent=4)

    items_file = Path(config.DATA_SHOPS_PATH / "shops-items-by-item.json")
    with open(items_file, 'w') as f:
        json.dump(dict(shops_by_item), f, indent=4)

    print(f">>> Exported structured data to {shops_file} and {items_file}")


if __name__ == "__main__":
    fetch()
    process()
