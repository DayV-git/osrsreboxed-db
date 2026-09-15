"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: scripts/dialogues/update.py

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

import json

import pytest

import config
from scripts.dialogues import update as dialogues_update


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Control-flow keywords are jumps, not gameplay the server must implement.
        ("{{tact|other}}", dict(type="jump", target=None, reference="other")),
        ("{{tact|continue}}", dict(type="jump", target=None, reference="continue")),
        ("{{tact|continues}}", dict(type="jump", target=None, reference="continues")),
        ("{{tact|below}}", dict(type="jump", target=None, reference="below")),
        ("{{tact|end}}", dict(type="end")),
        ("{{tact|members}}", dict(type="end", reason="members")),
        # Named parameters carry the gameplay payload; opens2 is the unlinked spelling.
        (
            "{{tact|opens=Bank}}",
            dict(type="action", action="open_interface", target="Bank"),
        ),
        (
            "{{tact|opens2=House style}}",
            dict(type="action", action="open_interface", target="House style"),
        ),
        (
            "{{tact|receives=a puzzle box}}",
            dict(type="action", action="receive", text="a puzzle box"),
        ),
        (
            "{{tact|gives=2 coins}}",
            dict(type="action", action="give", text="2 coins"),
        ),
    ],
)
def test_parse_step_tact(raw, expected):
    assert dialogues_update.parse_step(raw, [], 1) == expected


def test_gameplay_step_keeps_members_reason():
    node = dict(type="end", reason="members")
    assert dialogues_update.gameplay_step(node, "Asyff") == node


def test_unrecognised_tact_keyword_stays_an_action():
    issues = []
    node = dialogues_update.parse_step("{{tact|Player is teleported}}", issues, 1)
    assert node["type"] == "action"
    assert node["text"] == "Player is teleported"


@pytest.mark.parametrize(
    "text,expected",
    [
        # Inferred slugs always carry action_source so a consumer can ignore them.
        (
            "(Bank interface opens.)",
            dict(action="open_interface", action_source="text", target="Bank"),
        ),
        (
            "(Opens bank interface.)",
            dict(action="open_interface", action_source="text", target="bank"),
        ),
        (
            "(Game opens the Wise Old Man's Recycling Center interface)",
            dict(
                action="open_interface",
                action_source="text",
                target="Wise Old Man's Recycling Center",
            ),
        ),
        # A bare noun names no interface, so no target is emitted.
        ("Interface opens", dict(action="open_interface", action_source="text")),
        (
            "Bounty Hunter Store opens",
            dict(
                action="open_interface",
                action_source="text",
                target="Bounty Hunter Store",
            ),
        ),
        ("Player receives a lamp.", dict(action="receive", action_source="text")),
        (
            "The Vyrewatch teleports the player to the Meiyerditch mine",
            dict(action="teleport", action_source="text"),
        ),
        (
            "Player is taken to Fossil Island.",
            dict(action="teleport", action_source="text"),
        ),
        (
            "Sabreen heals you for 21 Hitpoints.",
            dict(action="heal", action_source="text"),
        ),
        ("The Butler bows", dict(action="emote", action_source="text")),
        (
            "If the player does not have enough coins:",
            dict(type="condition", action_source="text"),
        ),
        # The NPC moves, not the player: not a teleport.
        ("Yama snaps his fingers and teleports off his throne.", {}),
        ("Sune walks back to the pickaxe shop.", {}),
        ("Barlak gives you a short lecture.", {}),
        ("", {}),
    ],
)
def test_infer_action(text, expected):
    assert dialogues_update.infer_action(text) == expected


def test_inferred_condition_replaces_the_action_type():
    node = dialogues_update.parse_step("{{qact|If the player has no coins:}}", [], 1)
    assert node["type"] == "condition"
    assert node["action_source"] == "text"


def test_template_slugs_are_not_marked_as_inferred():
    node = dialogues_update.parse_step("{{tact|opens=Bank}}", [], 1)
    assert "action_source" not in node


@pytest.mark.parametrize(
    "target,shop",
    [
        # Decoration differs between a wiki link and the shop page title.
        ("Aubury's Rune Shop.", "Aubury's Rune Shop."),
        ("[[Zanaris General Store]]", "Zanaris General Store"),
        ("Slayer Equipment (shop){{!}}Slayer Equipment", "Slayer Equipment (shop)"),
        ("the fancy clothes store", "Fancy Clothes Store"),
        # Punctuation differs; the squashed key settles it.
        ("Trader Sven's Black Market Goods", "Trader Sven's Black-market Goods."),
        ("Al-Kharid General Store", "Al Kharid General Store"),
        # Case and a stray full stop, once the shops dump stopped emitting the
        # renamed pages that used to make both of these ambiguous.
        ("Betty's Magic Emporium.", "Betty's Magic Emporium"),
        ("The Pandemonium (Pub)", "The Pandemonium (pub)"),
    ],
)
def test_resolve_shops_retags_known_shops(target, shop):
    index = dialogues_update.shop_index()
    npcs = {"X": [dict(type="action", action="open_interface", target=target)]}
    assert dialogues_update.resolve_shops(npcs, index) == 1
    assert npcs["X"][0] == dict(type="action", action="open_shop", target=shop)


@pytest.mark.parametrize(
    "target", ["Bank", "Bank PIN", "Grand Exchange collection box"]
)
def test_resolve_shops_leaves_non_shops_alone(target):
    node = dict(type="action", action="open_interface", target=target)
    npcs = {"X": [node]}
    assert dialogues_update.resolve_shops(npcs, dialogues_update.shop_index()) == 0
    assert node["action"] == "open_interface"


def test_resolve_shops_keeps_the_inference_marker():
    npcs = {
        "X": [
            dict(
                type="action",
                action="open_interface",
                target="Zanaris General Store",
                action_source="text",
            )
        ]
    }
    dialogues_update.resolve_shops(npcs, dialogues_update.shop_index())
    assert npcs["X"][0]["action"] == "open_shop"
    assert npcs["X"][0]["action_source"] == "text"


def test_resolve_shops_is_a_no_op_without_an_index():
    node = dict(type="action", action="open_interface", target="Zanaris General Store")
    assert dialogues_update.resolve_shops({"X": [node]}, {}) == 0
    assert node["action"] == "open_interface"


def test_shop_index_drops_names_two_shops_share():
    # Quest-state variants fold onto the base name and cannot be told apart.
    index = dialogues_update.shop_index()
    assert index
    assert "gabooty's tai bwo wannai cooperative" not in index


def test_every_shop_keeps_its_literal_key():
    shops = json.loads((config.DOCS_PATH / dialogues_update.SHOPS).read_text())
    index = dialogues_update.shop_index()
    assert {shop: index.get(shop) for shop in shops} == {shop: shop for shop in shops}


def test_open_shop_targets_are_keys_of_the_shops_dump():
    shops = json.loads((config.DOCS_PATH / dialogues_update.SHOPS).read_text())
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    targets = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("action") == "open_shop":
                targets.add(node["target"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(dialogues)
    assert targets
    assert targets <= set(shops)
