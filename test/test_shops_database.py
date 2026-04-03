"""
Author: 0xNeffarion

Description:
Tests for shop JSON copying to docs.
"""

import json
from pathlib import Path

import config


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
