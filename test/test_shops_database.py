"""
Author:  DayV
Email:   dayv6842@gmail.com

Description:
Tests for shop JSON copying to docs.

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

import json
from pathlib import Path

import config
import validator


def test_shops_docs_json_exists_and_valid():
    """Ensure shops-items-by-shop and shops-items-by-item are copied into docs."""
    shops_by_shop = Path(config.DOCS_PATH / "shops-items-by-shop.json")
    shops_by_item = Path(config.DOCS_PATH / "shops-items-by-item.json")

    assert shops_by_shop.exists(), "docs/shops-items-by-shop.json must exist"
    assert shops_by_item.exists(), "docs/shops-items-by-item.json must exist"

    with open(shops_by_shop, "r", encoding="utf-8") as f:
        data_shop = json.load(f)
    with open(shops_by_item, "r", encoding="utf-8") as f:
        data_item = json.load(f)

    assert isinstance(data_shop, dict)
    assert isinstance(data_item, dict)

    # basic consistency check
    if data_item:
        first_item_id = next(iter(data_item))
        assert isinstance(data_item[first_item_id], list)


def test_shops_items_by_shop_schema_validation():
    """Validate shops-items-by-shop.json against schema."""
    # Read in the shops-items-by-shop schema file
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-shops-items-by-shop.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    # Validator object with schema attached
    v = validator.MyValidator(schema)

    # Read the shops-items-by-shop.json file
    path_to_shops_file = Path(config.DOCS_PATH / "shops-items-by-shop.json")
    with open(path_to_shops_file, "r", encoding="utf-8") as f:
        shops_data = json.load(f)

    # Validate each shop in the data
    for shop_name, shop_info in shops_data.items():
        assert v.validate(
            shop_info
        ), (
            f"Schema validation failed for shop: {shop_name}. "
            f"Errors: {v.errors}"
        )


def test_shops_items_by_item_schema_validation():
    """Validate shops-items-by-item.json against schema."""
    # Read in the shops-items-by-item schema file
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-shops-items-by-item.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    # Validator object with schema attached
    v = validator.MyValidator(schema)

    # Read the shops-items-by-item.json file
    path_to_shops_file = Path(config.DOCS_PATH / "shops-items-by-item.json")
    with open(path_to_shops_file, "r", encoding="utf-8") as f:
        shops_data = json.load(f)

    # Validate each item's shops in the data
    for item_id, shops_list in shops_data.items():
        assert isinstance(
            shops_list, list
        ), f"Item {item_id} should have a list of shops"
        for shop in shops_list:
            assert isinstance(
                shop, dict
            ), f"Each shop entry for item {item_id} should be a dict"
