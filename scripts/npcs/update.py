"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Program to generate the OSRS NPC interactions (click options) database.

Every NPC in the game cache carries up to five click options — the entries on
its right-click menu. This script reads those options out of a cache NPC
definition dump and exports them keyed by NPC ID, so consumers can tell what an
NPC does and in which menu slot:

    2817 Shop keeper -> {"1": "Talk-to", "3": "Trade"}

Slots are the cache's 1-based ``op1``..``op5``, and slots may be left empty:
the lowest numbered option present is the default left-click action. Molanisk,
for example, has only ``op2=Attack``, which is its left-click. Note that the
RuneLite-format ``ops`` array in ``data/monsters/monsters-cache-data.json`` is
0-based, so its index ``i`` is this file's slot ``i + 1``.

Input is a plain-text cache NPC dump (``dump.npc``), which is raw cache
material and therefore lives in the git-ignored ``data/cache/``. The generated
JSON under ``docs/`` is what gets committed.

Usage:
    python -m scripts.npcs.update
    python -m scripts.npcs.update --dump /path/to/dump.npc

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

import argparse
import collections
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, Optional

import config
from builders.run_log import begin_run

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_DUMP_FP = Path(config.DATA_CACHE_PATH / "dump.npc")

# Each record opens with the NPC ID as a comment, then its cache name.
RECORD_ID = re.compile(r"^//\s*(\d+)\s*$")
RECORD_NAME = re.compile(r"^\[(.+)\]\s*$")
# Click options, numbered by 1-based menu slot.
OPTION_FIELD = re.compile(r"^op([1-5])$")

# NPCs with no name are unused cache entries.
UNNAMED = {"", "null", "none"}


def parse_npc_dump(dump_path: Path) -> Iterator[Dict]:
    """Read NPC definitions out of a plain-text cache dump.

    The dump is a sequence of records, each opening with the NPC ID as a
    comment and its cache name in brackets, followed by ``key=value`` lines::

        // 2817
        [generalshopkeeper3]
        op1=Talk-to
        op3=Trade
        name=Shop keeper

    :param dump_path: Path to the ``dump.npc`` file.
    :return: Iterator of NPC dictionaries, one per record.
    """
    npc: Optional[Dict] = None

    with open(dump_path, encoding="utf-8", errors="replace") as dump_file:
        for line in dump_file:
            line = line.strip()
            if not line:
                continue

            id_match = RECORD_ID.match(line)
            if id_match:
                if npc is not None:
                    yield npc
                npc = {
                    "npc_id": int(id_match.group(1)),
                    "name": None,
                    "cache_name": None,
                    "options": {},
                }
                continue

            if npc is None:
                continue

            name_match = RECORD_NAME.match(line)
            if name_match:
                npc["cache_name"] = name_match.group(1)
                continue

            key, separator, value = line.partition("=")
            if not separator:
                continue
            key, value = key.strip().lower(), value.strip()

            option_match = OPTION_FIELD.match(key)
            if option_match:
                npc["options"][option_match.group(1)] = value
            elif key == "name":
                npc["name"] = value

    if npc is not None:
        yield npc


def generate(dump_path: Path, out_file: Path) -> None:
    """Export every NPC that has at least one click option.

    :param dump_path: Path to the cache NPC dump to read.
    :param out_file: Path of the JSON file to write.
    """
    if not dump_path.exists():
        raise SystemExit(
            f">>> ERROR: {dump_path} not found. Supply a cache NPC dump with --dump."
        )

    npcs = {}
    total = 0
    option_counts = collections.Counter()

    for npc in parse_npc_dump(dump_path):
        total += 1
        if not npc["options"]:
            continue
        if (npc["name"] or "").strip().lower() in UNNAMED:
            continue
        for slot in npc["options"]:
            option_counts[slot] += 1
        # Options are keyed by menu slot, so gaps in the slots survive.
        npc["options"] = {slot: npc["options"][slot] for slot in sorted(npc["options"])}
        npcs[npc["npc_id"]] = npc

    export = {
        "meta": {
            "generated": date.today().isoformat(),
            "source": "OSRS cache NPC definitions",
            "description": (
                "NPC click options, keyed by NPC ID. Option keys are the "
                "cache's 1-based menu slot (op1..op5); the lowest numbered "
                "option present is the default left-click action."
            ),
            "npc_count": len(npcs),
            "npcs_in_dump": total,
            "option_slot_counts": {
                slot: option_counts[slot] for slot in sorted(option_counts)
            },
        },
        "npcs": {str(npc_id): npcs[npc_id] for npc_id in sorted(npcs)},
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as json_file:
        json.dump(export, json_file, indent=2)

    logger.info(
        "Wrote %s (%d of %d NPCs have click options)", out_file, len(npcs), total
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate the OSRS NPC interactions (click options) database."
    )
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEFAULT_DUMP_FP,
        help="Path to the cache NPC dump (default: data/cache/dump.npc).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(config.DOCS_PATH / "npcs-interactions.json"),
        help="Path of the JSON file to write.",
    )
    args = parser.parse_args()

    begin_run("scripts_npcs_update")
    logger.info("Starting NPC interactions extraction...")
    generate(dump_path=args.dump, out_file=args.out)
    logger.info("NPC interactions extraction completed!")


if __name__ == "__main__":
    main()
