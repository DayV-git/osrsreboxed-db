"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: docs/npcs-interactions.json

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
from pathlib import Path

import config
import validator
from scripts.npcs import update as npcs_update

NPC_DUMP_RECORD = """// 2817
[generalshopkeeper3]
vislevel=0
walkanim=human_walk_f,human_walk_b
op1=Talk-to
op3=Trade
name=Shop keeper
// 1
[molanisk]
op2=Attack
name=Molanisk
"""


def _load():
    """Load the generated NPC interactions database."""
    with open(
        Path(config.DOCS_PATH / "npcs-interactions.json"), "r", encoding="utf-8"
    ) as f:
        return json.load(f)


def test_npc_dump_record_parsing(tmp_path):
    """Records yield the NPC ID, cache name, name and options by menu slot."""
    dump_file = tmp_path / "dump.npc"
    dump_file.write_text(NPC_DUMP_RECORD)

    npcs = {npc["npc_id"]: npc for npc in npcs_update.parse_npc_dump(dump_file)}

    assert npcs[2817]["name"] == "Shop keeper"
    assert npcs[2817]["cache_name"] == "generalshopkeeper3"
    assert npcs[2817]["options"] == {"1": "Talk-to", "3": "Trade"}
    # Empty slots are preserved: Attack sits in slot 2, with slot 1 unused.
    assert npcs[1]["options"] == {"2": "Attack"}


def test_npcs_interactions_exists_and_valid():
    """Ensure the NPC interactions database is generated into docs."""
    data = _load()
    assert set(data) == {"meta", "npcs"}
    assert data["meta"]["npc_count"] == len(data["npcs"])
    assert data["npcs"], "at least one NPC must have click options"


def test_npcs_interactions_schema_validation():
    """Validate every NPC in npcs-interactions.json against schema."""
    # Read in the npcs-interactions schema file
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-npcs-interactions.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    # Validator object with schema attached
    v = validator.MyValidator(schema)

    # Validate each NPC in the database
    for npc_id, npc in _load()["npcs"].items():
        assert npc["npc_id"] == int(npc_id)
        assert v.validate(npc), (
            f"Schema validation failed for NPC: {npc_id}. " f"Errors: {v.errors}"
        )


def test_option_slots_are_one_based():
    """Slots match the cache's 1-based op1..op5, not the 0-based RuneLite array.

    ``monsters-cache-data.json`` stores the same options 0-indexed, so a
    consumer joining the two files must add one. This asserts that offset
    holds, since silently drifting by a slot would misreport the left-click.

    The two files are dumped from different cache revisions, so this checks
    that the shifted options are a subset of ours rather than equal — an NPC
    may have gained an option in between. A 0-based reading satisfies the
    subset check for no NPC at all, so the offset is still pinned down.
    """
    interactions = _load()["npcs"]
    with open(
        Path(config.DATA_MONSTERS_PATH / "monsters-cache-data.json"),
        "r",
        encoding="utf-8",
    ) as f:
        monsters = json.load(f)

    compared = 0
    zero_based_matches = 0
    for npc_id, monster in monsters.items():
        ours = interactions.get(npc_id, {}).get("options")
        runelite_ops = (monster.get("ops") or {}).get("ops") or []
        if not ours or not runelite_ops:
            continue
        texts = {
            index: op["text"]
            for index, op in enumerate(runelite_ops)
            if isinstance(op, dict) and op.get("text")
        }
        if not texts:
            continue

        compared += 1
        shifted = {str(index + 1): text for index, text in texts.items()}
        assert (
            shifted.items() <= ours.items()
        ), f"option slots disagree for NPC {npc_id}"

        unshifted = {str(index): text for index, text in texts.items()}
        if unshifted.items() <= ours.items():
            zero_based_matches += 1

    assert compared > 100, "expected many monsters to cross-check against"
    assert zero_based_matches == 0, "a 0-based reading should never match"
