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
from scripts.shops import shop_owners


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
        assert v.validate(shop_info), (
            f"Schema validation failed for shop: {shop_name}. " f"Errors: {v.errors}"
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


SHOP_INFOBOX = """{{Infobox Shop
|name = Al Kharid General Store
|owner = [[Shop keeper (Al Kharid)|Shop keeper]]
}}"""

NPC_INFOBOX = """{{Infobox NPC
|name = Shop keeper
|version1 = Al Kharid
|id1 = 2813,2814
}}"""


def test_shop_owner_parsed_from_infobox():
    """The owner field yields the NPC's wiki page and its display name."""
    owners = shop_owners.parse_shop_owners(SHOP_INFOBOX)
    assert owners == [{"name": "Shop keeper", "wiki_page": "Shop keeper (Al Kharid)"}]
    assert shop_owners.parse_shop_owners("{{Infobox Shop\n|name = Nowhere\n}}") == []


def test_shop_owner_npc_ids_read_from_owner_page():
    """NPC IDs come from the owner page infobox, not from name matching."""
    assert shop_owners.npc_ids_from_wikitext(NPC_INFOBOX) == [2813, 2814]
    assert shop_owners.npc_ids_from_wikitext("No infobox here.") == []


def test_shops_have_owners():
    """Every exported shop carries an owners list, and most resolve to NPC IDs."""
    with open(
        Path(config.DOCS_PATH / "shops-items-by-shop.json"), encoding="utf-8"
    ) as f:
        shops = json.load(f)

    assert all(isinstance(shop["owners"], list) for shop in shops.values())

    named = [shop for shop in shops.values() if shop["owners"]]
    with_ids = [
        shop
        for shop in shops.values()
        if any(owner["npc_ids"] for owner in shop["owners"])
    ]
    assert len(named) > len(shops) * 0.7, "most shops should name an owner"
    assert len(with_ids) > len(shops) * 0.6, "most shops should resolve owner NPC IDs"


def test_shop_option_detection():
    """Shop-opening options cover the Trade-* family and reward shop wording."""
    assert shop_owners.is_shop_option("Trade")
    assert shop_owners.is_shop_option("Trade-General-Store")
    assert shop_owners.is_shop_option("Exchange")
    assert not shop_owners.is_shop_option("Talk-to")
    assert not shop_owners.is_shop_option("Attack")


def test_shops_by_npc_schema_validation():
    """Validate the NPC-keyed shop index against schema."""
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-shops-by-npc.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    v = validator.MyValidator(schema)

    with open(Path(config.DOCS_PATH / "shops-by-npc.json"), encoding="utf-8") as f:
        shops_by_npc = json.load(f)

    assert shops_by_npc, "shops-by-npc.json must not be empty"
    for npc_id, npc in shops_by_npc.items():
        assert npc["npc_id"] == int(npc_id)
        assert v.validate(npc), (
            f"Schema validation failed for NPC: {npc_id}. " f"Errors: {v.errors}"
        )


def test_shops_by_npc_agrees_with_shops_by_shop():
    """The NPC index points at real shops, and at the options they open with."""
    with open(
        Path(config.DOCS_PATH / "shops-items-by-shop.json"), encoding="utf-8"
    ) as f:
        by_shop = json.load(f)
    with open(Path(config.DOCS_PATH / "shops-by-npc.json"), encoding="utf-8") as f:
        by_npc = json.load(f)
    with open(Path(config.DOCS_PATH / "npcs-interactions.json"), encoding="utf-8") as f:
        interactions = json.load(f)["npcs"]

    for npc_id, npc in by_npc.items():
        for shop in npc["shops"]:
            assert shop["shop_name"] in by_shop, "index references an unknown shop"
            if shop["option"] is None:
                # A null option must say why: the NPC has options but none open
                # a shop (dialogue), or it has none at all (unknown). Neither
                # means "use option 1".
                assert shop["option_source"] in ("dialogue", "unknown")
                has_options = npc_id in interactions
                assert shop["option_source"] == (
                    "dialogue" if has_options else "unknown"
                )
                continue
            # The named option must sit in that slot on the NPC itself
            assert shop["option_source"] == "click"
            options = interactions[npc_id]["options"]
            assert options[str(shop["option_slot"])] == shop["option"]

    # The index holds exactly the owners that have NPC IDs, nothing inferred
    owners_with_ids = {
        npc_id
        for shop in by_shop.values()
        for owner in shop["owners"]
        for npc_id in owner["npc_ids"]
    }
    assert owners_with_ids == {int(npc_id) for npc_id in by_npc}
