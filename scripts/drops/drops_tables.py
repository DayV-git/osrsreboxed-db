"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Turns parsed OSRS Wiki drop lines into the npc drops JSON dump.

Resolves each drop's item ID against the project's own item database, works out
the weight and roll denominator of every table, and aggregates the result into
the three exported files:

    npc-drops.json      meta, drop tables, and the npcs that roll them
    subtables.json      shared tables (rare drop table, gem table, herbs, seeds)
    unresolved-items.json   drop names that matched no item in the database

Item and npc IDs come from the databases already in this repository, so no
game cache or third-party dump is needed.

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
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.drops import drops_wikitext as wikitext
from scripts.drops.drops_wikitext import (
    SECTION_GUARANTEED,
    SECTION_MAIN,
    SECTION_TERTIARY,
    ParsedDrop,
    ParsedDropTable,
)

logger = logging.getLogger(__name__)

# The wiki page holding every shared drop table.
SHARED_TABLE_PAGE = "Drop table"

# Shared tables, keyed by the name monster tables reference them with, mapped to
# the level-2 heading their drop lines live under on SHARED_TABLE_PAGE.
SHARED_TABLE_SECTIONS = [
    ("rareDrop", "Rare drop table", "rare drop table"),
    ("gem", "Gem drop table", "gem drop table"),
    ("megaRare", "Mega-rare drop table", "mega-rare drop table"),
    ("herb", "Herb drop table", "herb drop table"),
    ("usefulHerb", "Useful herb drop table", "useful herb drop table"),
    ("combatHerb", "Combat herb drop table", "combat herb drop table"),
    ("seed", "General seed drop table", "general seed drop table"),
    ("rareSeed", "Rare seed drop table", "rare seed drop table"),
    # Referenced from the gem table; monsters never roll it directly.
    ("talisman", "Talisman drop table", "talisman drop table"),
]

# Shared tables reference each other by display name (the rare drop table rolls
# the gem table on 20/128). Those rows are refs, not items.
NESTED_TABLE_REFS = {
    "rare drop table": "rareDrop",
    "gem drop table": "gem",
    "mega-rare drop table": "megaRare",
    "megarare drop table": "megaRare",
    "herb drop table": "herb",
    "seed drop table": "seed",
    "general seed drop table": "seed",
    "rare seed drop table": "rareSeed",
    "talisman": "talisman",
    "talisman drop table": "talisman",
}

PRE_ROLL_SUBSECTION = "Pre-roll"


@dataclass
class ResolvedEntry:
    """A drop line with its item ID and rate resolved."""

    item_id: Optional[int]
    name: str
    quantity: str
    weight: Optional[int] = None
    out_of: Optional[int] = None
    roll_denominator: Optional[int] = None
    subsection: str = ""
    rarity_raw: str = ""
    assumed_rarity: bool = False
    is_nothing: bool = False
    clue_scroll_box: bool = False
    brimstone_combat_roll: bool = False
    brimstone_konar_bonus: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class SeparateRoll:
    """Main-table drops rolled on their own denominator rather than the table pool."""

    subsection: str
    access_numerator: int
    access_denominator: int
    entries: List[ResolvedEntry]


@dataclass
class DropTableSpec:
    """A single resolved drop table, ready for export."""

    table_id: str
    label: str
    table_name: str
    wiki_page: str
    npc_ids: List[int]
    guaranteed: List[ResolvedEntry] = field(default_factory=list)
    pre_roll: List[ResolvedEntry] = field(default_factory=list)
    pre_roll_separate: List[SeparateRoll] = field(default_factory=list)
    main: List[ResolvedEntry] = field(default_factory=list)
    main_max_roll: Optional[int] = None
    separate_rolls: List[SeparateRoll] = field(default_factory=list)
    subtable_accesses: List[wikitext.ParsedSubtableAccess] = field(default_factory=list)
    tertiary: List[ResolvedEntry] = field(default_factory=list)
    unresolved_items: List[str] = field(default_factory=list)

    def has_drop_content(self) -> bool:
        """True when the table resolved to anything worth exporting."""
        return bool(
            self.guaranteed
            or self.main
            or self.pre_roll
            or self.pre_roll_separate
            or self.separate_rolls
            or self.subtable_accesses
            or self.tertiary
        )


# ---------------------------------------------------------------------------
# Item ID lookup
# ---------------------------------------------------------------------------


class ItemIdLookup:
    """Resolves wiki drop names to item IDs using the project's item database."""

    def __init__(self, items):
        """
        :param items: Iterable of osrsreboxed item objects.
        """
        # Wiki names are checked first: several items share a plain name
        # ("Coins" is 617, 995, 6964 and 8890) but their wiki names do not.
        self.by_wiki_name: Dict[str, int] = {}
        self.by_name: Dict[str, int] = {}
        # Where several items share a name, prefer the one players actually
        # trade ("Ensouled abyssal head (Item)" over "… (Drop)"), then the
        # lowest ID, which is the first of a numbered family such as the 138
        # elite clue scroll steps.
        for item in sorted(
            items, key=lambda entry: (not entry.tradeable_on_ge, entry.id)
        ):
            if item.duplicate or item.noted or item.placeholder or item.stacked:
                continue
            if item.wiki_name:
                self.by_wiki_name.setdefault(self._normalize(item.wiki_name), item.id)
            if item.name:
                self.by_name.setdefault(self._normalize(item.name), item.id)
        self.unresolved: Dict[str, int] = {}

    @staticmethod
    def _normalize(name: str) -> str:
        return re.sub(r"\s+", " ", name.strip().lower())

    def resolve(self, wiki_name: str) -> Optional[int]:
        """Look up the item ID for a wiki drop name.

        Wiki drop names carry qualifiers the item database writes differently,
        e.g. the version anchor in ``Bird nest (egg)#Blue egg``, so a few
        progressively looser forms are tried before giving up.

        :param wiki_name: The drop name as written on the wiki.
        :return: The item ID, or None when nothing matches.
        """
        for candidate in self._candidates(self._normalize(wiki_name)):
            item_id = self.by_wiki_name.get(candidate, self.by_name.get(candidate))
            if item_id is not None:
                return item_id
        self.unresolved[wiki_name] = self.unresolved.get(wiki_name, 0) + 1
        return None

    @staticmethod
    def _candidates(name: str):
        yield name
        # Anchors point at one version of a versioned item page:
        # "Bird nest (egg)#Blue egg" is wiki name "Bird nest (egg) (Blue egg)".
        if "#" in name:
            base, _, anchor = name.partition("#")
            base, anchor = base.strip(), anchor.strip()
            if base and anchor:
                yield f"{base} ({anchor})"
            if base:
                yield base
                name = base
        # Wiki disambiguators the item database does not carry.
        without_qualifier = re.sub(r"\s*\([^)]*\)$", "", name).strip()
        if without_qualifier and without_qualifier != name:
            yield without_qualifier
        if name.endswith("s"):
            yield name[:-1]


# ---------------------------------------------------------------------------
# Table naming
# ---------------------------------------------------------------------------


def display_wiki_page_name(wiki_page: str) -> str:
    """Turn an underscored wiki page key back into its display title."""
    return " ".join(part for part in wiki_page.split("_") if part)


def _wiki_page_base(wiki_page: str) -> str:
    parts = [re.sub(r"[^A-Za-z0-9]", "", part) for part in wiki_page.split("_") if part]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    head = parts[0][:1].lower() + parts[0][1:]
    return head + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _table_name_suffix(table_name: str) -> Optional[str]:
    if table_name.lower() == "drops":
        return None
    match = re.search(r"(\d+)", table_name)
    return match.group(1) if match else None


def _drop_variant_suffix(drop_variant: str) -> Optional[str]:
    if not drop_variant.strip():
        return None
    normalized = drop_variant.lower()
    if "wilderness" in normalized:
        return "Wilderness"
    if "catacombs" in normalized and "standard" not in normalized:
        return "Catacombs"
    parts = [
        re.sub(r"[^A-Za-z0-9]", "", part)
        for part in re.split(r"[\s,]+", drop_variant)
        if part and part.lower() != "and"
    ]
    suffix = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return suffix or None


def _camel_to_snake(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _table_id(wiki_page: str, table_name: str, drop_variant: str) -> str:
    suffix = _table_name_suffix(table_name) or _drop_variant_suffix(drop_variant)
    var_name = _wiki_page_base(wiki_page) + "DropTable" + (suffix or "")
    if var_name.endswith("DropTable"):
        var_name = var_name[: -len("DropTable")]
    return _camel_to_snake(var_name)


def _table_identifier(wiki_page: str, table_name: str, drop_variant: str) -> str:
    display_name = display_wiki_page_name(wiki_page)
    if drop_variant.strip():
        return f"{display_name} {drop_variant}"
    if table_name.lower() == "drops":
        return f"{display_name} Drops"
    return f"{display_name} {table_name}"


# ---------------------------------------------------------------------------
# Rate resolution
# ---------------------------------------------------------------------------


def _resolve_entry(drop: ParsedDrop, items: ItemIdLookup) -> Optional[ResolvedEntry]:
    """Resolve one parsed drop line into an export entry, or None to skip it."""
    if drop.is_nothing:
        if drop.section != SECTION_MAIN:
            return None
        rate = wikitext.parse_main_rarity(drop.rarity)
        if rate is None:
            return None
        weight, roll_denominator = rate
        return ResolvedEntry(
            item_id=None,
            name=drop.name,
            quantity="1",
            weight=weight,
            roll_denominator=roll_denominator,
            subsection=drop.subsection,
            is_nothing=True,
        )

    if not wikitext.has_known_drop_rate(drop.rarity):
        return None

    item_id = items.resolve(drop.name)
    if item_id is None:
        return None

    entry = ResolvedEntry(
        item_id=item_id,
        name=drop.name,
        quantity=drop.quantity,
        subsection=drop.subsection,
        rarity_raw=drop.rarity,
        assumed_rarity=drop.assumed_rarity,
        clue_scroll_box=drop.clue_scroll_box,
        notes=list(drop.notes),
    )

    if drop.section == SECTION_GUARANTEED:
        return entry
    if drop.section == SECTION_MAIN:
        rate = wikitext.parse_main_rarity(drop.rarity)
        if rate is None:
            return None
        entry.weight, entry.roll_denominator = rate
        return entry

    # Tertiary
    if wikitext.is_brimstone_rarity(drop.rarity):
        entry.brimstone_combat_roll = True
        entry.brimstone_konar_bonus = wikitext.has_brimstone_konar_bonus(drop.rarity)
        return entry
    rate = wikitext.parse_tertiary_rarity(drop.rarity)
    if rate is None:
        return None
    entry.weight, entry.out_of = rate
    return entry


def _finalize_main_rolls(
    main: List[ResolvedEntry], subtable_accesses: List[wikitext.ParsedSubtableAccess]
) -> Tuple[List[ResolvedEntry], Optional[int], List[SeparateRoll]]:
    """Split main-table drops into the shared pool and their own separate rolls.

    Drops are written against whatever denominator the wiki used, so the most
    populated denominator becomes the table's pool and everything else becomes
    an independent roll.

    :param main: Resolved main-table entries.
    :param subtable_accesses: Shared table accesses on the same table.
    :return: A (pool entries, pool denominator, separate rolls) tuple.
    """
    if not main:
        return [], (subtable_accesses[0].denominator if subtable_accesses else None), []

    default_denominator = subtable_accesses[0].denominator if subtable_accesses else 128
    by_denominator: Dict[int, List[ResolvedEntry]] = {}
    for entry in main:
        denominator = entry.roll_denominator or default_denominator
        by_denominator.setdefault(denominator, []).append(entry)

    primary = max(
        by_denominator.items(),
        key=lambda item: (
            len(item[1]),
            sum(entry.weight or 0 for entry in item[1]),
            -item[0],
        ),
    )[0]

    separate_rolls = []
    for denominator, entries in by_denominator.items():
        if denominator == primary:
            continue
        by_subsection: Dict[str, Dict[int, List[ResolvedEntry]]] = {}
        for entry in entries:
            subsection = entry.subsection or "Other"
            by_subsection.setdefault(subsection, {}).setdefault(
                entry.weight or 1, []
            ).append(entry)
        for subsection, by_weight in by_subsection.items():
            for weight, weight_entries in by_weight.items():
                separate_rolls.append(
                    SeparateRoll(subsection, weight, denominator, weight_entries)
                )

    return by_denominator[primary], primary, separate_rolls


def build_table_spec(
    wiki_page: str, table: ParsedDropTable, items: ItemIdLookup
) -> DropTableSpec:
    """Resolve a parsed drop table into an exportable spec.

    :param wiki_page: Underscored wiki page key the table came from.
    :param table: The parsed table.
    :param items: Item ID lookup.
    :return: The resolved :class:`DropTableSpec`.
    """
    guaranteed: List[ResolvedEntry] = []
    main: List[ResolvedEntry] = []
    tertiary: List[ResolvedEntry] = []
    unresolved: List[str] = []

    # Seed drops are listed individually and as a shared table access on some
    # pages; the access wins so the seeds are not counted twice.
    has_seed_access = any(
        access.table_key in ("seed", "rareSeed") for access in table.subtable_accesses
    )

    for drop in table.drops:
        if has_seed_access and drop.subsection.lower() == "seeds":
            continue
        entry = _resolve_entry(drop, items)
        if entry is None:
            if not drop.is_nothing and wikitext.has_known_drop_rate(drop.rarity):
                unresolved.append(drop.name)
            continue
        if drop.section == SECTION_GUARANTEED:
            guaranteed.append(entry)
        elif drop.section == SECTION_TERTIARY:
            tertiary.append(entry)
        else:
            main.append(entry)

    pre_roll_drops = []
    standard_main = []
    for entry in main:
        if entry.subsection.lower() == PRE_ROLL_SUBSECTION.lower():
            pre_roll_drops.append(entry)
        else:
            standard_main.append(entry)

    pre_roll, _, pre_roll_separate = _finalize_main_rolls(pre_roll_drops, [])
    main_entries, main_max_roll, separate_rolls = _finalize_main_rolls(
        standard_main, table.subtable_accesses
    )
    if main_max_roll is not None:
        used = sum(entry.weight or 0 for entry in main_entries) + sum(
            access.numerator for access in table.subtable_accesses
        )
        main_max_roll = max(main_max_roll, used)

    return DropTableSpec(
        table_id=_table_id(wiki_page, table.table_name, table.drop_variant),
        label=(table.drop_variant or table.table_name or "Drops"),
        table_name=_table_identifier(wiki_page, table.table_name, table.drop_variant),
        wiki_page=display_wiki_page_name(wiki_page),
        npc_ids=table.npc_ids,
        guaranteed=guaranteed,
        pre_roll=pre_roll,
        pre_roll_separate=pre_roll_separate,
        main=main_entries,
        main_max_roll=main_max_roll,
        separate_rolls=separate_rolls,
        subtable_accesses=table.subtable_accesses,
        tertiary=tertiary,
        unresolved_items=list(dict.fromkeys(unresolved)),
    )


# ---------------------------------------------------------------------------
# JSON shaping
# ---------------------------------------------------------------------------


def _without_nulls(values: Dict, keep=()) -> Dict:
    return {
        key: value for key, value in values.items() if value is not None or key in keep
    }


def _rarity(weight: Optional[int], out_of: Optional[int]) -> Optional[float]:
    """Chance of a single roll landing on an entry, to seven decimal places."""
    if weight is None or out_of is None or out_of <= 0:
        return None
    return round((weight / out_of) * 10_000_000) / 10_000_000


def _parse_quantity(raw: str) -> Optional[List[int]]:
    """``"1"`` -> [1, 1]; ``"3-5"`` -> [3, 5]; anything else stays raw."""
    trimmed = raw.strip().replace(",", "")
    if not trimmed:
        return None
    if re.fullmatch(r"\d+", trimmed):
        return [int(trimmed), int(trimmed)]
    match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", trimmed)
    if not match:
        return None
    return [int(match.group(1)), int(match.group(2))]


def _entry_json(
    entry: ResolvedEntry,
    out_of: Optional[int],
    always: bool = False,
    separate: bool = False,
    pre_roll: bool = False,
) -> Optional[Dict]:
    if entry.is_nothing:
        return _without_nulls(
            {"nothing": True, "weight": entry.weight, "out_of": out_of}
        )
    if not entry.name:
        return None

    quantity = _parse_quantity(entry.quantity)
    rarity = _rarity(entry.weight if entry.weight is not None else 1, out_of)

    return _without_nulls(
        {
            "item_id": entry.item_id,
            "name": entry.name,
            "quantity": quantity,
            "quantity_raw": (
                entry.quantity if entry.quantity and quantity is None else None
            ),
            "always": True if always else None,
            "pre_roll": True if pre_roll else None,
            "separate_roll": True if separate else None,
            "weight": entry.weight,
            "out_of": out_of,
            "rarity": rarity,
            "rarity_raw": (
                entry.rarity_raw if entry.rarity_raw and rarity is None else None
            ),
            "section": entry.subsection or None,
            "clue_scroll_box": True if entry.clue_scroll_box else None,
            "assumed_rarity": True if entry.assumed_rarity else None,
            "notes": entry.notes or None,
        },
        keep=("item_id",),
    )


def build_table_json(spec: DropTableSpec) -> Dict:
    """Shape a resolved drop table into its exported JSON form."""
    entries = []
    for entry in spec.guaranteed:
        row = _entry_json(entry, out_of=None, always=True)
        if row:
            entries.append(row)
    for entry in spec.pre_roll:
        row = _entry_json(entry, out_of=entry.out_of, pre_roll=True)
        if row:
            entries.append(row)
    for entry in spec.main:
        row = _entry_json(entry, out_of=entry.out_of or spec.main_max_roll)
        if row:
            entries.append(row)
    for access in spec.subtable_accesses:
        entries.append(
            _without_nulls(
                {
                    "shared_table": access.table_key,
                    "weight": access.numerator,
                    "out_of": access.denominator,
                    "rarity": _rarity(access.numerator, access.denominator),
                    "section": access.subsection or None,
                },
                keep=("rarity",),
            )
        )
    for rolls, is_pre_roll in (
        (spec.separate_rolls, False),
        (spec.pre_roll_separate, True),
    ):
        for roll in rolls:
            for entry in roll.entries:
                row = _entry_json(
                    entry,
                    out_of=entry.out_of or roll.access_denominator,
                    separate=True,
                    pre_roll=is_pre_roll,
                )
                if row:
                    entries.append(row)

    tertiary = []
    for entry in spec.tertiary:
        if entry.brimstone_combat_roll or entry.brimstone_konar_bonus:
            continue
        row = _entry_json(entry, out_of=entry.out_of)
        if row:
            tertiary.append(row)

    return _without_nulls(
        {
            "table_id": spec.table_id,
            "label": spec.label or "Drops",
            "table_name": spec.table_name,
            "wiki_page": spec.wiki_page,
            "main_max_roll": spec.main_max_roll,
            "entries": entries,
            "tertiary": tertiary,
            "brimstone_key_roll": (
                True
                if any(entry.brimstone_combat_roll for entry in spec.tertiary)
                else None
            ),
            "brimstone_konar_bonus": (
                True
                if any(entry.brimstone_konar_bonus for entry in spec.tertiary)
                else None
            ),
            # Kept as names rather than dropping the whole table.
            "unresolved_items": spec.unresolved_items or None,
        }
    )


class NpcDropsAggregator:
    """Collects drop tables across every monster page and writes the dump.

    Output is keyed by npc ID, each holding the IDs of the tables it rolls, so
    monsters with several drop tables (variants, difficulty tiers) keep all of
    them.
    """

    def __init__(self, npc_names: Optional[Dict[int, str]] = None):
        """
        :param npc_names: Optional npc ID to cache name mapping.
        """
        self.npc_names = npc_names or {}
        self.npcs: Dict[int, Dict] = {}
        self.tables: Dict[str, Dict] = {}
        self.shared_refs = set()
        self.unresolved_items = set()
        self.table_count = 0

    def add(self, spec: DropTableSpec) -> None:
        """Register a resolved drop table and the npcs that roll it."""
        table = build_table_json(spec)
        self.table_count += 1
        table_id = self._register_table(table)

        for access in spec.subtable_accesses:
            self.shared_refs.add(access.table_key)
        self.unresolved_items.update(spec.unresolved_items)

        for npc_id in spec.npc_ids:
            npc = self.npcs.get(npc_id)
            if npc is None:
                npc = _without_nulls(
                    {
                        "npc_id": npc_id,
                        "name": spec.wiki_page,
                        # Cache name, useful for telling variant IDs apart where
                        # the wiki page is shared.
                        "cache_name": self.npc_names.get(npc_id),
                        "wiki_page": spec.wiki_page,
                        "tables": [],
                    }
                )
                self.npcs[npc_id] = npc
            if table_id not in npc["tables"]:
                npc["tables"].append(table_id)

    def _register_table(self, table: Dict) -> str:
        """Store a table once and return the ID npcs should reference.

        Table IDs come from wiki page names, so two genuinely different tables
        can derive the same ID. Those get a numeric suffix rather than silently
        overwriting one another.
        """
        base = table["table_id"]
        table_id = base
        suffix = 2
        while True:
            existing = self.tables.get(table_id)
            if existing is None:
                self.tables[table_id] = {**table, "table_id": table_id}
                return table_id
            if existing == {**table, "table_id": table_id}:
                return table_id
            table_id = f"{base}_{suffix}"
            suffix += 1

    def write(self, out_dir: Path, subtables: Dict, wiki_pages_scanned: int) -> None:
        """Write the three dump files to ``out_dir``.

        :param out_dir: Directory to write into (created if missing).
        :param subtables: Shared subtable export, from :func:`export_shared_subtables`.
        :param wiki_pages_scanned: Number of wiki pages processed, for the meta block.
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "generated": date.today().isoformat(),
            "source": "https://oldschool.runescape.wiki",
            "license": "CC BY-NC-SA 3.0 — content from the Old School RuneScape Wiki",
            "id_space": "osrs cache ids (item and npc ids from the osrsreboxed databases)",
            "npc_count": len(self.npcs),
            "table_count": len(self.tables),
            "table_refs": sum(len(npc["tables"]) for npc in self.npcs.values()),
            "wiki_pages_scanned": wiki_pages_scanned,
            "shared_tables": sorted(self.shared_refs),
            "unresolved_item_count": len(self.unresolved_items),
        }

        npcs = {str(npc_id): self.npcs[npc_id] for npc_id in sorted(self.npcs)}
        tables = {table_id: self.tables[table_id] for table_id in sorted(self.tables)}

        with open(out_dir / "npc-drops.json", "w") as out_file:
            json.dump(
                {"meta": meta, "tables": tables, "npcs": npcs}, out_file, indent=2
            )
        with open(out_dir / "subtables.json", "w") as out_file:
            json.dump(subtables, out_file, indent=2)
        with open(out_dir / "unresolved-items.json", "w") as out_file:
            json.dump(sorted(self.unresolved_items), out_file, indent=2)


# ---------------------------------------------------------------------------
# Shared subtables
# ---------------------------------------------------------------------------

ANY_HEADING = re.compile(r"^(=+)\s*([^=\n]+?)\s*=+[ \t]*$", re.M)


def _section_body(page_wikitext: str, heading: str) -> Optional[str]:
    """Return the body under a heading, ending at the next same-or-higher heading."""
    match = re.search(
        r"^(=+)\s*" + re.escape(heading) + r"\s*=+[ \t]*$", page_wikitext, re.I | re.M
    )
    if not match:
        return None
    level = len(match.group(1))
    rest = page_wikitext[match.end() :]
    for following in ANY_HEADING.finditer(rest):
        if len(following.group(1)) <= level:
            return rest[: following.start()]
    return rest


def export_shared_subtables(page_wikitext: Optional[str], items: ItemIdLookup) -> Dict:
    """Extract the shared drop tables from the wiki's ``Drop table`` page.

    Shared tables are referenced by name from monster entries and emitted once
    here, rather than inlined into every monster that rolls them.

    :param page_wikitext: Wikitext of the ``Drop table`` page, or None.
    :param items: Item ID lookup.
    :return: Dictionary of shared table name to its entries.
    """
    subtables = {}
    for key, heading, wiki_label in SHARED_TABLE_SECTIONS:
        entries = []
        body = _section_body(page_wikitext, heading) if page_wikitext else None
        for _, params in wikitext.extract_templates(body or "", "DropsLine"):
            name = params.get("name")
            if not name:
                continue
            quantity = params.get("quantity", "")
            rarity = params.get("rarity", "")
            nested = NESTED_TABLE_REFS.get(name.strip().lower())
            if nested and nested != key:
                entries.append(
                    {"shared_table": nested, "name": name, "rarity_raw": rarity}
                )
            elif name.strip().lower() == "nothing":
                entries.append({"nothing": True, "rarity_raw": rarity})
            else:
                entries.append(
                    {
                        "item_id": items.resolve(name),
                        "name": name,
                        "quantity_raw": quantity,
                        "rarity_raw": rarity,
                    }
                )
        if not entries:
            logger.debug(
                "shared table '%s' — no entries extracted from '%s'",
                key,
                SHARED_TABLE_PAGE,
            )
        subtables[key] = {
            "name": key,
            "wiki_label": wiki_label,
            "wiki_page": SHARED_TABLE_PAGE,
            "entries": entries,
        }
    return subtables
