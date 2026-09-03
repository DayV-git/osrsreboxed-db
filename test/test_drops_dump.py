"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: scripts/drops

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

from scripts.drops import drops_tables, drops_wikitext


class FakeItem:
    """Stand-in for an osrsreboxed item, so the tests need no item database."""

    def __init__(self, item_id, name, wiki_name=None, tradeable_on_ge=True):
        self.id = item_id
        self.name = name
        self.wiki_name = wiki_name or name
        self.tradeable_on_ge = tradeable_on_ge
        self.duplicate = False
        self.noted = False
        self.placeholder = False
        self.stacked = None


ITEMS = drops_tables.ItemIdLookup(
    [
        FakeItem(526, "Bones"),
        FakeItem(995, "Coins"),
        FakeItem(617, "Coins", "Coins (Shilo Village)", tradeable_on_ge=False),
        FakeItem(1163, "Rune full helm"),
        FakeItem(11286, "Draconic visage"),
        FakeItem(5072, "Bird nest", "Bird nest (egg) (Blue egg)"),
    ]
)

WIKITEXT = """
{{Infobox Monster
|id1 = 123,124
|version1 = Normal
}}

==Drops==
===100%===
{{DropsLine|name=Bones|quantity=1|rarity=Always}}

===Weapons and armour===
{{DropsLine|name=Rune full helm|quantity=1|rarity=3/128}}
{{DropsLine|name=Coins|quantity=100-200|rarity=1/128}}
{{DropsLine|name=Nothing|rarity=123/128}}
{{RareDropTable|1/128}}
{{DropsLine|name=Bird nest (egg)#Blue egg|quantity=1|rarity=Common}}

===Tertiary===
{{DropsLine|name=Draconic visage|quantity=1|rarity=1/{{#expr:5000/(1)}}
|raritynotes=Only dropped in [[Wilderness|the Wilderness]].}}

==Other==
"""


def _table():
    tables = drops_wikitext.parse_all_drop_tables(WIKITEXT)
    assert len(tables) == 1
    return drops_tables.build_table_json(
        drops_tables.build_table_spec("Test_monster", tables[0], ITEMS)
    )


def test_npc_ids_come_from_the_infobox():
    """Both IDs on the infobox roll the page's single drop table."""
    tables = drops_wikitext.parse_all_drop_tables(WIKITEXT)
    assert tables[0].npc_ids == [123, 124]


def test_table_identity():
    """Table naming follows the wiki page, not the npc."""
    table = _table()
    assert table["table_id"] == "test_monster"
    assert table["table_name"] == "Test monster Drops"
    assert table["wiki_page"] == "Test monster"
    assert table["label"] == "Drops"


def test_guaranteed_drop_has_no_rate():
    """A 100% drop is exported as always, with no weight or roll."""
    entry = _table()["entries"][0]
    assert entry["item_id"] == 526
    assert entry["always"] is True
    assert "weight" not in entry and "out_of" not in entry


def test_main_table_weights_share_one_denominator():
    """Every main table drop is weighted against the same pool."""
    table = _table()
    assert table["main_max_roll"] == 128
    entries = [e for e in table["entries"] if e.get("out_of") == 128]
    assert [e.get("name") for e in entries] == [
        "Rune full helm",
        "Coins",
        None,  # the Nothing roll
        None,  # the rare drop table access
    ]
    assert entries[0]["weight"] == 3
    assert entries[0]["rarity"] == 0.0234375
    assert entries[1]["quantity"] == [100, 200]
    assert entries[2]["nothing"] is True
    assert entries[3]["shared_table"] == "rareDrop"


def test_item_ids_prefer_the_wiki_name():
    """ "Coins" is four items; the one the wiki links to wins."""
    coins = [e for e in _table()["entries"] if e.get("name") == "Coins"][0]
    assert coins["item_id"] == 995


def test_version_anchors_resolve_to_the_right_item():
    """``Bird nest (egg)#Blue egg`` is the blue egg item, not the base nest."""
    nest = [
        e for e in _table()["entries"] if e.get("name", "").startswith("Bird nest")
    ][0]
    assert nest["item_id"] == 5072
    # A word rarity is a convention, not wiki data, so it is flagged.
    assert nest["assumed_rarity"] is True
    # Its 1/8 rate is not the table pool, so it rolls separately.
    assert nest["separate_roll"] is True
    assert nest["out_of"] == 8


def test_tertiary_rate_is_evaluated_and_annotated():
    """Wiki arithmetic resolves to a rate, and footnotes travel with the drop."""
    tertiary = _table()["tertiary"][0]
    assert tertiary["item_id"] == 11286
    assert tertiary["out_of"] == 5000
    assert tertiary["notes"] == ["Only dropped in the Wilderness."]


def test_expression_evaluation_rejects_non_arithmetic():
    """The expression evaluator only ever evaluates arithmetic."""
    assert drops_wikitext.evaluate_expression("2000/(1999/2000) round 1") == "2001"
    assert drops_wikitext.evaluate_expression("__import__('os')") is None


def test_shared_table_accesses_are_not_double_counted():
    """A table that rolls the seed table drops its individually listed seeds."""
    wikitext = """{{Infobox Monster\n|id1 = 1\n}}\n==Drops==\n"""
    wikitext += "===Seeds===\n{{GeneralSeedDropTableInfo|18/128}}\n"
    wikitext += "{{DropsLine|name=Coins|quantity=1|rarity=1/128}}\n"
    table = drops_wikitext.parse_all_drop_tables(wikitext)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test_monster", table, ITEMS)
    )
    assert [e.get("shared_table") for e in exported["entries"]] == ["seed"]
