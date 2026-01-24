"""
Author:  DayV
Email:   dayv6842@gmail.com

Description:
Base builder class for shared logic between entity builders (items, monsters).
Provides common initialization, run/test loops, and error handling patterns.

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

import traceback
from abc import ABC, abstractmethod


class BaseBuilder(ABC):
    """Abstract base class for entity builders with common logic."""
    
    def __init__(self, **kwargs):
        """Initialize builder with common control flags.
        
        Args:
            verbose (bool): Enable verbose output
            compare (bool): Compare new vs old entity data
            export (bool): Export entity data to JSON files
            validate (bool): Validate entities against schema
        """
        self.verbose = kwargs.get("verbose", False)
        self.compare = kwargs.get("compare", False)
        self.export = kwargs.get("export", False)
        self.validate = kwargs.get("validate", False)
        
        # Load entity-specific data files via abstract method
        self._load_data_files()
    
    @abstractmethod
    def _load_data_files(self):
        """Load all required data files for this entity type.
        
        Subclasses must implement this to load entity-specific data.
        Should set attributes like self.all_cache_data, self.all_db_data, etc.
        """
        pass
    
    @abstractmethod
    def _get_entity_id_list(self):
        """Get the list of entity IDs to process.
        
        Returns:
            list or dict: Entity IDs from the cache data
        """
        pass
    
    @abstractmethod
    def _should_skip_entity(self, entity_id):
        """Check if an entity should be skipped during processing.
        
        Args:
            entity_id: The entity ID to check
            
        Returns:
            bool: True if entity should be skipped
        """
        pass
    
    @abstractmethod
    def _build_entity(self, entity_id):
        """Build a single entity.
        
        Args:
            entity_id: The entity ID to build
            
        Returns:
            Builder object with the built entity (e.g., BuildItem or BuildMonster)
        """
        pass
    
    @abstractmethod
    def _process_built_entity(self, builder, entity_id):
        """Process a built entity after building.
        
        Args:
            builder: The entity builder object (e.g., BuildItem instance)
            entity_id: The entity ID that was built
        """
        pass
    
    def run(self):
        """Run the build process for all entities."""
        try:
            entity_ids = list(self._get_entity_id_list())
            total_entities = len(entity_ids)
            entities_processed = 0
            
            print(f">>> Starting build process for {total_entities} entities...")
            printed_milestones = set()
            
            for entity_id in entity_ids:
                try:
                    if self._should_skip_entity(entity_id):
                        continue
                    
                    entities_processed += 1
                    
                    # Calculate and print progress at 25% intervals (once each)
                    progress_pct = (entities_processed / total_entities) * 100
                    for milestone in [25, 50, 75, 100]:
                        if progress_pct >= milestone and milestone not in printed_milestones:
                            printed_milestones.add(milestone)
                            print(f"  > Progress: {entities_processed:4d} of {total_entities:4d} ({progress_pct:.1f}%)")
                            break
                    
                    builder = self._build_entity(entity_id)
                    self._process_built_entity(builder, entity_id)
                    
                except Exception:
                    print(f"Ran into issue parsing entity {entity_id}.")
                    print(traceback.format_exc())
                    with open(".error.txt", "a", encoding="utf-8") as errfile:
                        print(f"Ran into issue parsing entity {entity_id}.", file=errfile)
                        print(traceback.format_exc(), file=errfile)
            
            # Done processing, rejoice!
            print("Built.")
            exit(0)
            
        except Exception:
            print("Fatal error during build process.")
            print(traceback.format_exc())
            with open(".error.txt", "a", encoding="utf-8") as errfile:
                print("Fatal error during build process.", file=errfile)
                print(traceback.format_exc(), file=errfile)
            exit(1)
    
    def test(self):
        """Run the test process for all entities (validation only)."""
        try:
            entity_ids = list(self._get_entity_id_list())
            total_entities = len(entity_ids)
            entities_processed = 0
            
            print(f">>> Starting test process for {total_entities} entities...")
            printed_milestones = set()
            
            for entity_id in entity_ids:
                try:
                    if self._should_skip_entity(entity_id):
                        continue
                    
                    entities_processed += 1
                    
                    # Calculate and print progress at 25% intervals (once each)
                    progress_pct = (entities_processed / total_entities) * 100
                    for milestone in [25, 50, 75, 100]:
                        if progress_pct >= milestone and milestone not in printed_milestones:
                            printed_milestones.add(milestone)
                            print(f"  > Progress: {entities_processed:4d} of {total_entities:4d} ({progress_pct:.1f}%)")
                            break
                    
                    builder = self._build_entity(entity_id)
                    self._process_built_entity_test(builder, entity_id)
                    
                except Exception:
                    print(f"Ran into issue parsing entity {entity_id}.")
                    print(traceback.format_exc())
                    with open(".error.txt", "a", encoding="utf-8") as errfile:
                        print(f"Ran into issue parsing entity {entity_id}.", file=errfile)
                        print(traceback.format_exc(), file=errfile)
            
            # Done testing, rejoice!
            print("Tested.")
            exit(0)
            
        except Exception:
            print("Fatal error during test process.")
            print(traceback.format_exc())
            with open(".error.txt", "a", encoding="utf-8") as errfile:
                print("Fatal error during test process.", file=errfile)
                print(traceback.format_exc(), file=errfile)
            exit(1)
    
    def _process_built_entity_test(self, builder, entity_id):
        """Process a built entity in test mode (validation only).
        
        Default implementation validates only. Subclasses can override.
        
        Args:
            builder: The entity builder object
            entity_id: The entity ID that was built
        """
        # Default test mode behavior - just validate
        if hasattr(builder, 'validate_item'):
            builder.validate_item()
        elif hasattr(builder, 'validate_monster'):
            builder.validate_monster()
