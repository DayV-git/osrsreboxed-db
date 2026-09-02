"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: docs/drops-json

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


def _load(file_name: str):
    """Load one of the generated drops dump files."""
    with open(Path(config.DOCS_DROPS_PATH / file_name), "r", encoding="utf-8") as f:
        return json.load(f)


def test_drops_docs_json_exists_and_valid():
    """Ensure the drops dump files are generated into docs."""
    for file_name in ("npc-drops.json", "subtables.json", "unresolved-items.json"):
        assert Path(
            config.DOCS_DROPS_PATH / file_name
        ).exists(), f"docs/drops-json/{file_name} must exist"

    npc_drops = _load("npc-drops.json")
    assert set(npc_drops) == {"meta", "tables", "npcs"}
    assert npc_drops["meta"]["table_count"] == len(npc_drops["tables"])
    assert npc_drops["meta"]["npc_count"] == len(npc_drops["npcs"])
    assert isinstance(_load("unresolved-items.json"), list)


def test_drops_schema_validation():
    """Validate every drop table in npc-drops.json against schema."""
    # Read in the drops schema file
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-drops.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    # Validator object with schema attached
    v = validator.MyValidator(schema)

    # Validate each drop table in the dump
    for table_id, table in _load("npc-drops.json")["tables"].items():
        assert v.validate(table), (
            f"Schema validation failed for drop table: {table_id}. "
            f"Errors: {v.errors}"
        )


def test_npcs_reference_known_tables():
    """Every NPC points at drop tables that exist in the same file."""
    npc_drops = _load("npc-drops.json")
    tables = npc_drops["tables"]

    for npc_id, npc in npc_drops["npcs"].items():
        assert npc["npc_id"] == int(npc_id)
        assert npc["tables"], f"npc {npc_id} has no drop tables"
        for table_id in npc["tables"]:
            assert (
                table_id in tables
            ), f"npc {npc_id} references unknown table {table_id}"


def test_shared_tables_are_exported():
    """Every shared table a drop table rolls into is defined in subtables.json."""
    npc_drops = _load("npc-drops.json")
    subtables = _load("subtables.json")

    for table_id, table in npc_drops["tables"].items():
        for entry in table["entries"]:
            shared_table = entry.get("shared_table")
            # The empty key is a multi-roll herb table, which has no single
            # shared table to point at.
            if shared_table:
                assert (
                    shared_table in subtables
                ), f"drop table {table_id} rolls undefined shared table {shared_table}"
