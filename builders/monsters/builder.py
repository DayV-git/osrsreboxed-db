"""
Author:  PH01L
Email:   phoil@osrsbox.com
Website: https://www.osrsbox.com

Description:
Program to invoke monster database generation process.

Copyright (c) 2021, PH01L

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
import argparse
from pathlib import Path

import config
from builders.base_builder import BaseBuilder
from builders.monsters import build_monster


class Builder(BaseBuilder):
    """Monster-specific builder that extends BaseBuilder."""
    
    def _load_data_files(self):
        """Load all monster-specific data files."""
        # Load the raw cache data that has been processed (this is ground truth)
        with open(Path(config.DATA_MONSTERS_PATH / "monsters-cache-data.json")) as f:
            self.all_monster_cache_data = json.load(f)

        # Load all monster data (from min JSON file)
        with open(Path(config.DOCS_PATH / "monsters-complete.json")) as f:
            self.all_db_monsters = json.load(f)

        # Load the monster wikitext file of page text
        with open(
            Path(config.DATA_MONSTERS_PATH / "monsters-wiki-page-text.json")
        ) as f:
            self.all_wikitext_raw = json.load(f)

        # Load the monster wikitext file of processed data
        with open(
            Path(config.DATA_MONSTERS_PATH / "monsters-wiki-page-text-processed.json")
        ) as f:
            self.all_wikitext_processed = json.load(f)

        # Load schema data
        with open(Path(config.DATA_SCHEMAS_PATH / "schema-monsters.json")) as f:
            self.schema_data = json.load(f)

        # Initialize a list of known monsters
        self.known_monsters = []
    
    def _get_entity_id_list(self):
        """Get list of monster IDs from cache data."""
        return self.all_monster_cache_data
    
    def _should_skip_entity(self, monster_id):
        """Check if monster should be skipped."""
        # No skipping logic for monsters
        return False
    
    def _build_entity(self, monster_id):
        """Build a single monster."""
        return build_monster.BuildMonster(
            monster_id=monster_id,
            all_monster_cache_data=self.all_monster_cache_data,
            all_db_monsters=self.all_db_monsters,
            all_wikitext_raw=self.all_wikitext_raw,
            all_wikitext_processed=self.all_wikitext_processed,
            schema_data=self.schema_data,
            known_monsters=self.known_monsters,
            verbose=self.verbose,
        )
    
    def _process_built_entity(self, builder, monster_id):
        """Process a built monster."""
        status, message = builder.preprocessing()
        if status:
            builder.populate_monster()
            known_monster = builder.check_duplicate_monster()
            self.known_monsters.append(known_monster)
            
            if self.compare:
                builder.compare_new_vs_old_monster()
            if self.export:
                builder.export_monster_to_json()
            if self.validate:
                builder.validate_monster()
        else:
            with open(".error.txt", "a", encoding="utf-8") as errfile:
                print(message, file=errfile)
    
    def _process_built_entity_test(self, builder, monster_id):
        """Process a built monster in test mode."""
        status, message = builder.preprocessing()
        if status:
            builder.populate_monster()
            known_monster = builder.check_duplicate_monster()
            self.known_monsters.append(known_monster)
            builder.validate_monster()
        else:
            with open(".error.txt", "a", encoding="utf-8") as errfile:
                print(message, file=errfile)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build monster database.")
    parser.add_argument(
        "--verbose",
        default=False,
        action="store_true",
        help="Enable verbose output.",
    )
    parser.add_argument(
        "--compare",
        default=False,
        action="store_true",
        help="Compare new vs old monster data.",
    )
    parser.add_argument(
        "--export",
        default=False,
        action="store_true",
        help="Export monster data to JSON files.",
    )
    parser.add_argument(
        "--validate",
        default=False,
        action="store_true",
        help="Validate monsters against schema.",
    )
    parser.add_argument(
        "--test",
        default=False,
        action="store_true",
        help="Run in test mode (validation only).",
    )
    args = parser.parse_args()

    builder = Builder(
        verbose=args.verbose, 
        compare=args.compare, 
        export=args.export, 
        validate=args.validate
    )
    if args.test:
        builder.test()
    else:
        builder.run()
