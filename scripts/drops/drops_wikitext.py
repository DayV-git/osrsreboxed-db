"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Parsing of OSRS Wiki monster drop tables from raw wikitext.

Turns the ``==Drops==`` sections of a monster page into structured drop lines:
one :class:`ParsedDrop` per ``{{DropsLine}}`` / ``{{DropsLineClue}}`` template,
plus the shared-table accesses (rare drop table, gem table, herb tables, seed
tables) the page rolls into. Rarities written as wiki arithmetic
(``{{#expr:}}`` / ``{{#var:}}``) are evaluated here; word rarities ("Common",
"Rare") resolve to a documented convention and are flagged as assumed.

This is a port of the OpenRune-Server wiki drop dumper
(``tools/wiki-dumping``), reduced to what the JSON dump needs and detached from
that project's cache/gameval lookups.

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

import ast
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

import mwparserfromhell

# Drop sections, in the sense the wiki uses them (not the JSON export shape).
SECTION_GUARANTEED = "Guaranteed"
SECTION_MAIN = "Main"
SECTION_TERTIARY = "Tertiary"

# Shared drop tables a monster page can roll into. The key is the name used in
# the JSON export; the label is how the wiki refers to the table in prose.
SUBTABLE_LABELS = {
    "herb": "herb drop table",
    # Multi-roll herb tables have no single shared table to point at, so they
    # keep the empty key the Kotlin exporter used.
    "": "multi-roll herb drop table",
    "usefulHerb": "useful herb drop table",
    "combatHerb": "combat herb drop table",
    "gem": "gem drop table",
    "seed": "general seed drop table",
    "rareSeed": "rare seed drop table",
    "rareDrop": "rare drop table",
    "megaRare": "mega-rare drop table",
}


@dataclass
class ParsedDrop:
    """A single ``{{DropsLine}}`` row."""

    name: str
    quantity: str
    rarity: str
    section: str
    subsection: str = ""
    assumed_rarity: bool = False
    is_nothing: bool = False
    is_noted: bool = False
    notes: List[str] = field(default_factory=list)
    clue_scroll_box: bool = False


@dataclass
class ParsedSubtableAccess:
    """A roll from a monster's main table into a shared drop table."""

    table_key: str
    numerator: int
    denominator: int
    subsection: str


@dataclass
class ParsedDropTable:
    """One drop table on a wiki page (a page can carry several)."""

    table_name: str
    drop_variant: str
    drops: List[ParsedDrop]
    subtable_accesses: List[ParsedSubtableAccess]
    npc_ids: List[int]


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def template_params(template) -> Dict[str, str]:
    """Map a wikitext template's parameters to a dictionary.

    Named parameters are lowercased; positional parameters are keyed ``_0``,
    ``_1``, ... in the order they appear.

    :param template: A mwparserfromhell template object.
    :return: Dictionary of parameter name to value.
    """
    params: Dict[str, str] = {}
    positional = 0
    for param in template.params:
        value = str(param.value).strip()
        if param.showkey:
            params[str(param.name).strip().lower()] = value
        else:
            params[f"_{positional}"] = value
            positional += 1
    return params


def extract_templates(
    wikitext: str, template_name: str
) -> List[Tuple[str, Dict[str, str]]]:
    """Extract every instance of a named template from wikitext.

    :param wikitext: Raw wikitext to search.
    :param template_name: Template name to match (case insensitive).
    :return: List of (raw parameter text, parsed parameters) tuples.
    """
    wanted = template_name.lower()
    found = []
    for template in mwparserfromhell.parse(wikitext).filter_templates():
        if str(template.name).strip().lower() != wanted:
            continue
        raw = "|".join(str(param) for param in template.params)
        found.append((raw, template_params(template)))
    return found


def _first_fraction(raw: str) -> Optional[Tuple[int, int]]:
    """Read the first ``n/m`` fraction out of a string."""
    match = re.search(r"(\d+)\s*/\s*(\d+)", raw.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------------------
# Rarity resolution
# ---------------------------------------------------------------------------

# Conventional RS rarity buckets. These are assumptions, not wiki data — every
# drop that uses one is flagged `assumed_rarity` in the export so it can be
# found and overridden.
ASSUMED_RATES = {
    "common": 8,
    "uncommon": 32,
    "rare": 128,
    "very rare": 512,
    # No meaningful bucket; treated as rare so the drop exists rather than
    # vanishing.
    "varies": 128,
    "random": 128,
    "unknown": 128,
}

# Clue scroll base rates are monster-specific on the wiki; these are per-tier
# fallbacks only.
ASSUMED_CLUE_RATES = {
    "beginner": 50,
    "easy": 128,
    "medium": 150,
    "hard": 256,
    "elite": 500,
    "master": 750,
}

VAR_DEFINE_HEAD = re.compile(r"\{\{\s*#vardefine(?:echo)?\s*:\s*([^|}]+)\|", re.I)
VAR_USE = re.compile(r"\{\{\s*#var\s*:\s*([^|}]+?)\s*(?:\|[^}]*)?\}\}", re.I)
EXPR = re.compile(r"\{\{\s*#expr\s*:\s*([^{}]*)\}\}", re.I)
ROUND_SUFFIX = re.compile(r"\s+round\s+(-?\d+)\s*$", re.I)


def collect_page_vars(wikitext: str) -> Dict[str, str]:
    """Collect ``{{#vardefine:}}`` values declared anywhere on a page.

    :param wikitext: Raw wikitext of the page.
    :return: Dictionary of variable name (lowercased) to raw value.
    """
    page_vars = {}
    for match in VAR_DEFINE_HEAD.finditer(wikitext):
        value = _read_balanced(wikitext, match.end())
        if value is None:
            continue
        page_vars[match.group(1).strip().lower()] = value.strip()
    return page_vars


def _read_balanced(text: str, start: int) -> Optional[str]:
    """Read up to the ``}}`` closing an already-open template, honouring nesting."""
    depth = 1
    index = start
    out = []
    while index < len(text):
        if text.startswith("{{", index):
            depth += 1
            out.append("{{")
            index += 2
        elif text.startswith("}}", index):
            depth -= 1
            if depth == 0:
                return "".join(out)
            out.append("}}")
            index += 2
        else:
            out.append(text[index])
            index += 1
    return None


def evaluate_expression(expression: str) -> Optional[str]:
    """Evaluate wiki ``#expr`` arithmetic: ``+ - * / ( )`` and a trailing ``round n``.

    :param expression: The expression body, without the surrounding template.
    :return: The evaluated value as plain text, or None if it cannot be evaluated.
    """
    trimmed = expression.strip()
    if not trimmed or _contains_markup(trimmed):
        return None

    round_match = ROUND_SUFFIX.search(trimmed)
    body = trimmed[: round_match.start()] if round_match else trimmed
    places = int(round_match.group(1)) if round_match else -1

    value = _arithmetic(body)
    if value is None or not math.isfinite(value):
        return None

    quantum = Decimal(1).scaleb(-(places if places >= 0 else 6))
    try:
        scaled = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return format(scaled.normalize(), "f")


def _arithmetic(body: str) -> Optional[float]:
    """Evaluate a plain arithmetic expression, returning None on anything unexpected."""
    if not re.fullmatch(r"[\d\s.+\-*/()]+", body or ""):
        return None
    try:
        node = ast.parse(body, mode="eval").body
    except SyntaxError:
        return None
    try:
        return _eval_node(node)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _eval_node(node) -> float:
    """Evaluate a whitelisted arithmetic AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _eval_node(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("unsupported expression")


def _contains_markup(text: str) -> bool:
    return "{{" in text or "}}" in text or "#expr" in text or "#var" in text


def _expand(text: str, page_vars: Dict[str, str], depth: int = 0) -> Optional[str]:
    """Substitute ``#var`` then evaluate ``#expr``, innermost first."""
    if depth > 8:
        return None

    changed = False

    def replace_var(match):
        nonlocal changed
        value = page_vars.get(match.group(1).strip().lower())
        if value is None:
            return match.group(0)
        changed = True
        return f"({value})"

    def replace_expr(match):
        nonlocal changed
        value = evaluate_expression(match.group(1))
        if value is None:
            return match.group(0)
        changed = True
        return value

    current = EXPR.sub(replace_expr, VAR_USE.sub(replace_var, text))
    if not changed:
        return current
    return _expand(current, page_vars, depth + 1)


def resolve_rarity(
    rarity: str, item_name: str, page_vars: Dict[str, str]
) -> Optional[Tuple[str, bool]]:
    """Resolve a wiki rarity field into plain ``n/m`` text.

    :param rarity: The raw rarity field from the drop line.
    :param item_name: Drop name, used only to pick a clue scroll tier fallback.
    :param page_vars: Variables declared on the page, from :func:`collect_page_vars`.
    :return: A (rarity text, assumed) tuple, or None when it cannot be resolved.
    """
    raw = rarity.strip()
    if not raw:
        return None

    # "Always" is load-bearing downstream (guaranteed drops key off it).
    if raw.lower() == "always":
        return None

    expanded = _expand(raw, page_vars)
    if (
        expanded
        and not _contains_markup(expanded)
        and any(c.isdigit() for c in expanded)
    ):
        return expanded, False

    assumed = _assumed_rate_for(raw, item_name)
    if assumed is not None:
        return f"1/{assumed}", True
    return None


def _assumed_rate_for(raw: str, item_name: str) -> Optional[int]:
    label = raw.lower().strip()
    if label not in ASSUMED_RATES and not any(
        label.startswith(k) for k in ASSUMED_RATES
    ):
        return None

    name = item_name.lower()
    if "clue scroll" in name:
        for tier, rate in ASSUMED_CLUE_RATES.items():
            if tier in name:
                return rate

    if label in ASSUMED_RATES:
        return ASSUMED_RATES[label]
    for key, rate in ASSUMED_RATES.items():
        if label.startswith(key):
            return rate
    return None


# ---------------------------------------------------------------------------
# Drop rate parsing
# ---------------------------------------------------------------------------

DECIMAL_FRACTION_RARITY = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
BRIMSTONE_RARITY_TEMPLATE = re.compile(r"\{\{\s*Brimstone\s+rarity\s*\|\s*(\d+)", re.I)
BRIMSTONE_BONUS_FLAG = re.compile(r"(?:\|\s*bonus\s*=\s*yes|\|\s*yes\s*\}\})", re.I)


def is_brimstone_rarity(rarity: str) -> bool:
    """True when a rarity uses the combat-level scaled brimstone key template."""
    return bool(BRIMSTONE_RARITY_TEMPLATE.search(rarity.strip()))


def has_brimstone_konar_bonus(rarity: str) -> bool:
    """True when a brimstone key rarity carries the Konar task bonus flag."""
    return bool(BRIMSTONE_BONUS_FLAG.search(rarity))


def has_known_drop_rate(rarity: str) -> bool:
    """True when a rarity field carries a usable numeric rate."""
    trimmed = rarity.strip()
    if not trimmed:
        return False
    if trimmed.lower() == "always":
        return True
    if is_brimstone_rarity(trimmed):
        return True
    if _contains_markup(trimmed):
        return False
    if DECIMAL_FRACTION_RARITY.search(trimmed):
        return True
    return bool(re.fullmatch(r"-?\d+", trimmed))


def _parse_decimal_fraction(trimmed: str) -> Optional[Tuple[int, int]]:
    match = DECIMAL_FRACTION_RARITY.search(trimmed)
    if not match:
        return None
    numerator = int(
        Decimal(match.group(1)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    denominator = int(
        Decimal(match.group(2)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    return numerator, denominator


def parse_main_rarity(rarity: str) -> Optional[Tuple[int, int]]:
    """Parse a main-table rarity into a (weight, roll denominator) pair."""
    if not has_known_drop_rate(rarity) or rarity.strip().lower() == "always":
        return None
    fraction = _parse_decimal_fraction(rarity.strip())
    if fraction:
        return fraction
    if re.fullmatch(r"-?\d+", rarity.strip()):
        weight = int(rarity.strip())
        return weight, weight
    return None


def parse_tertiary_rarity(rarity: str) -> Optional[Tuple[int, int]]:
    """Parse a tertiary rarity into a (weight, out of) pair."""
    if rarity.strip().lower() == "always":
        return 1, 1
    if not has_known_drop_rate(rarity):
        return None
    return _parse_decimal_fraction(rarity.strip())


# ---------------------------------------------------------------------------
# Drop line notes
# ---------------------------------------------------------------------------

WIKI_LINK = re.compile(r"\[\[([^|\]]+)")
F2P_NOTE = re.compile(r"free[\s-]*to[\s-]*play", re.I)
F2P_ONLY_DROP = re.compile(
    r"only dropped in(?:\s*\[\[)?\s*free[\s-]*to[\s-]*play", re.I
)
F2P_NAME_NOTE = re.compile(r"\(f\)", re.I)
F2P_REF_NAME = re.compile(r"name\s*=\s*['\"]f2p['\"]", re.I)
TRANSFORM_ITEM_NOTE = re.compile(
    r"scroll\s*box|x\s*marks\s*the\s*spot|replaced\s*by", re.I
)
TRANSFORM_RATE_NOTE = re.compile(
    r"drop\s*rate|increases\s*to|decreases\s*to|\d+\s*/\s*\d+", re.I
)
LOOTING_BAG_WILDERNESS_NOTE = re.compile(
    r"looting\s*bags?\s*are\s*only\s*dropped.*wilderness", re.I
)
BRIMSTONE_KONAR_NOTE = re.compile(
    r"brimstone\s*keys?\s*are\s*only\s*dropped.*"
    r"(?:konar\s*quo\s*maten|slayer\s*task\s*given\s*by\s*konar)",
    re.I,
)
CLUE_SCROLL_BOX_NOTE = re.compile(r"scroll box", re.I)


@dataclass
class DropNotes:
    """Drop line footnotes, split by the kind of thing they say."""

    condition: List[str] = field(default_factory=list)
    transform_rate: List[str] = field(default_factory=list)
    transform_item: List[str] = field(default_factory=list)
    looting_bag_wilderness: bool = False
    brimstone_konar_task: bool = False
    quest_requirements: List[str] = field(default_factory=list)

    def as_list(self) -> List[str]:
        """Flatten to the note list used by the JSON export, preserving order."""
        notes = (
            list(self.condition) + list(self.transform_rate) + list(self.transform_item)
        )
        if self.looting_bag_wilderness:
            notes.append("Only dropped in the Wilderness (looting bag)")
        if self.brimstone_konar_task:
            notes.append("Konar task bonus")
        notes.extend(
            f"Quest requirement: {requirement}"
            for requirement in self.quest_requirements
        )
        return list(dict.fromkeys(note.strip() for note in notes if note.strip()))

    def has_clue_scroll_box(self) -> bool:
        """True when a footnote says the drop arrives as a clue scroll box."""
        return any(CLUE_SCROLL_BOX_NOTE.search(note) for note in self.transform_item)


def clean_wiki_notes(raw: str) -> str:
    """Strip templates, tags and link markup from a footnote, leaving plain text.

    :param raw: Raw footnote wikitext.
    :return: Plain text, or an empty string when nothing is left.
    """
    if not raw or not raw.strip():
        return ""
    text = raw.strip()
    text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)$", r"\1", text)
    text = text.replace("[[", "").replace("]]", "")
    return re.sub(r"\s+", " ", text).strip()


def classify_note(note: str, drop_name: str = "") -> DropNotes:
    """Sort a single footnote into the note category it belongs to.

    :param note: Cleaned footnote text.
    :param drop_name: The drop the note is attached to.
    :return: A :class:`DropNotes` holding just this note.
    """
    cleaned = note.strip()
    if not cleaned or F2P_NOTE.search(cleaned):
        return DropNotes()

    if LOOTING_BAG_WILDERNESS_NOTE.search(cleaned):
        return DropNotes(looting_bag_wilderness=True)
    if "looting bag" in drop_name.lower() and re.search(r"wilderness", cleaned, re.I):
        return DropNotes(looting_bag_wilderness=True)
    if BRIMSTONE_KONAR_NOTE.search(cleaned):
        return DropNotes(brimstone_konar_task=True)

    quest_requirement = parse_quest_requirement(cleaned)
    if quest_requirement:
        return DropNotes(quest_requirements=[quest_requirement])

    if TRANSFORM_ITEM_NOTE.search(cleaned):
        return DropNotes(transform_item=[cleaned])
    if TRANSFORM_RATE_NOTE.search(cleaned):
        return DropNotes(transform_rate=[cleaned])
    return DropNotes(condition=[cleaned])


def classify_notes(notes: List[str], drop_name: str) -> DropNotes:
    """Sort every footnote on a drop line into note categories."""
    merged = DropNotes()
    for note in notes:
        classified = classify_note(note, drop_name)
        for attribute in (
            "condition",
            "transform_rate",
            "transform_item",
            "quest_requirements",
        ):
            existing = getattr(merged, attribute)
            for value in getattr(classified, attribute):
                if value not in existing:
                    existing.append(value)
        merged.looting_bag_wilderness |= classified.looting_bag_wilderness
        merged.brimstone_konar_task |= classified.brimstone_konar_task
    return merged


NON_QUEST_NOTE = re.compile(r"\bdiary\b|quest variant|unowned during", re.I)
NOT_COMPLETED_NOTE = re.compile(
    r"(?:only\s+)?(?:dropped\s+)?(?:if\s+)?(?:[\w\s']+\s+)?"
    r"(?:isn't|is\s+not|aren't|are\s+not|haven't|has\s+not(?:\s+been)?)\s+completed",
    re.I,
)
NOT_COMPLETED_QUEST_NAME = re.compile(
    r"if\s+(.+?)\s+(?:isn't|is\s+not|aren't|are\s+not|haven't|has\s+not(?:\s+been)?)\s+completed",
    re.I,
)
AFTER_COMPLETION_NOTE = re.compile(
    r"(?:only\s+)?(?:dropped\s+)?(?:after\s+completion\s+of|after\s+completing|upon\s+completion\s+of)",
    re.I,
)
DURING_NOTE = re.compile(
    r"(?:only\s+)?(?:dropped\s+)?(?:when\s+fought\s+)?during(?:\s+the)?(?:\s+quest)?\s+",
    re.I,
)
ONLY_DURING_NOTE = re.compile(r"only\s+during\s+", re.I)
QUEST_LINK = re.compile(r"\[\[([^|\]#]+)")

# Quests whose slug does not fall out of the wiki name.
QUEST_KEY_OVERRIDES = {
    "monkey madness ii": "quest_monkeymadness2",
    "rag and bone man i": "quest_ragandboneman1",
    "rag and bone man ii": "quest_ragandboneman2",
    "dragon slayer i": "quest_dragonslayer1",
    "the fremennik trials": "quest_fremenniktrials",
    "underground pass": "quest_undergroundpass",
    "grim tales": "quest_grimtales",
    "legends' quest": "quest_legendsquest",
    "roving elves": "quest_rovingelves",
    "tree gnome village": "quest_treegnomevillage",
    "eagles' peak": "quest_eaglespeak",
    "priest in peril": "quest_priestinperil",
    "between a rock": "quest_betweenarock",
    "rum deal": "quest_rumdeal",
    "the great brain robbery": "quest_greatbrainrobbery",
    "one small favour": "quest_onesmallfavour",
    "desert treasure i": "quest_deserttreasure1",
    "lunar diplomacy": "quest_lunardiplomacy",
    "troll stronghold": "quest_trollstronghold",
    "observatory quest": "quest_observatoryquest",
    "x marks the spot": "quest_xmarksthespot",
}


def parse_quest_requirement(note: str) -> Optional[str]:
    """Read a quest gate out of a footnote.

    The returned string keeps the shape the Kotlin dumper emitted so existing
    consumers of the dump can keep parsing it.

    :param note: Cleaned footnote text.
    :return: A ``WikiQuestDropRequirement(...)`` string, or None.
    """
    cleaned = note.strip()
    if not cleaned or NON_QUEST_NOTE.search(cleaned):
        return None

    if NOT_COMPLETED_NOTE.search(cleaned):
        mode = "RequiresNotCompleted"
    elif AFTER_COMPLETION_NOTE.search(cleaned):
        mode = "RequiresCompleted"
    elif DURING_NOTE.search(cleaned) or ONLY_DURING_NOTE.search(cleaned):
        mode = "RequiresDuring"
    else:
        return None

    quest_name = _extract_quest_name(cleaned, mode)
    if not quest_name:
        return None
    return (
        f"WikiQuestDropRequirement(questKey={_to_quest_key(quest_name)}, mode={mode})"
    )


def _extract_quest_name(note: str, mode: str) -> Optional[str]:
    for match in QUEST_LINK.finditer(note):
        title = _clean_quest_title(match.group(1).strip())
        if len(title) >= 3 and title.lower() != "quest":
            return title

    raw = None
    if mode == "RequiresNotCompleted":
        match = NOT_COMPLETED_QUEST_NAME.search(note)
        raw = match.group(1).strip() if match else None
    elif mode == "RequiresCompleted":
        match = AFTER_COMPLETION_NOTE.search(note)
        raw = note[match.end() :].strip() if match else None
    else:
        match = DURING_NOTE.search(note) or ONLY_DURING_NOTE.search(note)
        raw = note[match.end() :].strip() if match else None
    if not raw:
        return None

    title = _clean_quest_title(raw.split(".")[0].split(",")[0].split(" if ")[0].strip())
    if len(title) < 3 or title.lower() == "quest":
        return None
    return title


def _clean_quest_title(title: str) -> str:
    return re.sub(r"\s*\(quest\)\s*", " ", title, flags=re.I).strip()


def _to_quest_key(wiki_name: str) -> str:
    cleaned = wiki_name.strip().rstrip(".").strip()
    normalized = re.sub(r"[^a-z0-9']+", " ", cleaned.lower()).strip()
    if normalized in QUEST_KEY_OVERRIDES:
        return QUEST_KEY_OVERRIDES[normalized]
    return "quest_" + re.sub(r"[^a-z0-9']+", "", cleaned.lower()).replace("'", "")


# ---------------------------------------------------------------------------
# Footnote extraction
# ---------------------------------------------------------------------------

GROUP_D_REF = re.compile(
    r"<ref[^>]*group\s*=\s*['\"]?d['\"]?[^>/]*>(.*?)</ref>", re.I | re.S
)
GROUP_D_TAG_REF = re.compile(r"\{\{#tag:ref\|([^|}]+)\|[^}]*group\s*=\s*d", re.I)
NAMED_REF = re.compile(r"<ref\s+([^>]*?)>(.*?)</ref>", re.I | re.S)
SELF_CLOSING_REF = re.compile(r"<ref\s+([^>]*?)/>", re.I)
REF_NAME = re.compile(r"name\s*=\s*['\"]([^'\"]+)['\"]", re.I)
REFN_TEMPLATE = re.compile(r"\{\{Refn\|[^}]*\}\}", re.I)
GROUP_D_REF_TAG_STRIP = re.compile(r"<ref[^>]*group\s*=\s*['\"]?d['\"]?[^>]*/?>", re.I)


def collect_named_footnotes(section_body: str) -> Dict[str, str]:
    """Collect ``<ref name="…" group="d">…</ref>`` footnote bodies from a section.

    Definitions embedded in a ``{{DropsLine}}`` note field count too, since the
    wiki often defines a footnote on the first drop line that uses it.

    :param section_body: Wikitext of one drop subsection.
    :return: Dictionary of ref name to cleaned footnote text.
    """
    refs = _parse_named_footnotes(section_body)
    for _, params in extract_templates(section_body, "DropsLine"):
        for field_name in ("namenotes", "raritynotes"):
            value = params.get(field_name, "")
            if not value.strip():
                continue
            for name, text in _parse_named_footnotes(value).items():
                refs.setdefault(name, text)
    return refs


def _parse_named_footnotes(section_body: str) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    for match in NAMED_REF.finditer(section_body):
        attrs = match.group(1)
        if not re.search(r"group", attrs, re.I) or "d" not in attrs.lower():
            continue
        name_match = REF_NAME.search(attrs.strip())
        if not name_match:
            continue
        text = clean_wiki_notes(match.group(2))
        if text:
            refs.setdefault(name_match.group(1).strip(), text)
    return refs


def parse_inline_note_fields(*fields: str) -> List[str]:
    """Read the footnotes written inline in ``namenotes`` / ``raritynotes``."""
    notes: List[str] = []
    for value in fields:
        if not value or not value.strip():
            continue
        for _, params in extract_templates(value, "Refn"):
            text = _refn_note(params)
            if text:
                notes.append(text)
        for match in GROUP_D_REF.finditer(value):
            text = clean_wiki_notes(match.group(1))
            if text:
                notes.append(text)
        stripped = GROUP_D_REF_TAG_STRIP.sub(" ", REFN_TEMPLATE.sub(" ", value))
        text = clean_wiki_notes(stripped)
        if text:
            notes.append(text)
    return list(dict.fromkeys(notes))


def _refn_note(params: Dict[str, str]) -> Optional[str]:
    group = params.get("group")
    if group is not None and group.lower() != "d":
        return None
    text = params.get("_0") or params.get("note") or params.get("1")
    if not text:
        return None
    return clean_wiki_notes(text) or None


def _resolve_named_ref_links(
    name_notes: str, rarity_notes: str, named_refs: Dict[str, str]
) -> List[str]:
    if not named_refs:
        return []
    combined = f"{name_notes} {rarity_notes}"
    resolved = []
    for match in SELF_CLOSING_REF.finditer(combined):
        attrs = match.group(1)
        if not re.search(r"group", attrs, re.I) or "d" not in attrs.lower():
            continue
        name_match = REF_NAME.search(attrs.strip())
        if not name_match:
            continue
        note = named_refs.get(name_match.group(1).strip())
        if note:
            resolved.append(note)
    return resolved


def _note_mentions_item(drop_name: str, note: str) -> bool:
    normalized_drop = _normalize_item_name(drop_name)
    if not normalized_drop:
        return False
    for match in WIKI_LINK.finditer(note):
        candidate = _normalize_item_name(match.group(1))
        if candidate and (
            normalized_drop == candidate
            or normalized_drop in candidate
            or candidate in normalized_drop
        ):
            return True
    return normalized_drop in _normalize_item_name(note)


def _relevant_to_drop(drop_name: str, note: str) -> bool:
    """Decide whether a shared footnote actually applies to this drop line."""
    name = drop_name.lower()
    text = note.lower()

    if "looting bag" in text or ("wilderness" in text and "bag" in text):
        return "looting bag" in name
    if "key" in text and "medium" in text:
        return "key" in name
    if TRANSFORM_ITEM_NOTE.search(text) or ("clue" in text and "scroll" in text):
        return "clue scroll" in name
    if TRANSFORM_RATE_NOTE.search(text) and "easy" in text:
        return "clue scroll" in name and "easy" in name
    if TRANSFORM_RATE_NOTE.search(text) and "clue" in text:
        return "clue scroll" in name
    if "free-to-play" in text or "free to play" in text:
        return False
    if "increases to" in text or "decreases to" in text:
        return name == "nothing"
    return _note_mentions_item(drop_name, note)


def _normalize_item_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _should_skip_f2p_drop(params: Dict[str, str], attached_notes: List[str]) -> bool:
    """F2P-only drops do not exist on members worlds, so they are dropped."""
    if (
        params.get("f2p", "").lower() == "yes"
        or params.get("leaguef2p", "").lower() == "yes"
    ):
        return True
    name_notes = params.get("namenotes", "")
    rarity_notes = params.get("raritynotes", "")
    if F2P_NAME_NOTE.search(name_notes):
        return True
    if F2P_REF_NAME.search(f"{name_notes} {rarity_notes}"):
        return True
    return any(F2P_ONLY_DROP.search(note) for note in attached_notes)


# ---------------------------------------------------------------------------
# Clue scroll drop lines
# ---------------------------------------------------------------------------

SCROLL_BOX_NOTE = (
    "Clue scrolls will drop as scroll boxes after the completion of X Marks the Spot."
)


def _clue_notes(
    drop_name: str,
    clue_type: str,
    rarity: str,
    note_override: Optional[str],
    rarity_notes: Optional[str],
) -> DropNotes:
    """Rebuild the footnotes Module:DropsLineClue injects at render time."""
    notes = []
    if note_override and note_override.strip():
        notes.append(clean_wiki_notes(note_override))
    else:
        if clue_type.lower() != "beginner":
            combat_achievement_note = _combat_achievement_rate_note(clue_type, rarity)
            if combat_achievement_note:
                notes.append(combat_achievement_note)
        notes.append(SCROLL_BOX_NOTE)
    if rarity_notes and rarity_notes.strip():
        notes.append(clean_wiki_notes(rarity_notes))
    return classify_notes(notes, drop_name)


def _combat_achievement_rate_note(clue_type: str, rarity: str) -> Optional[str]:
    match = re.search(r"([\d.]+)/([\d.]+)", rarity.strip())
    if not match:
        return None
    try:
        numerator = float(match.group(1))
        denominator = float(match.group(2))
    except ValueError:
        return None
    if numerator <= 0 or denominator <= 0:
        return None

    if numerator > 1:
        reduced = denominator / numerator
        adjusted = f"1/{int(math.floor(reduced - (reduced * 0.05)))}"
    else:
        adjusted = (
            f"{int(numerator)}/{int(math.floor(denominator - (denominator * 0.05)))}"
        )

    return (
        f"The {clue_type} clue scroll drop rate increases to {adjusted} after unlocking "
        f"the {clue_type} Combat Achievements rewards tier."
    )


# ---------------------------------------------------------------------------
# NPC IDs
# ---------------------------------------------------------------------------

NPC_INFOBOX_START = re.compile(r"\{\{Infobox\s+(?:Monster|NPC)\b", re.I)
VERSIONED_ID_FIELD = re.compile(r"\|\s*id(\d+)\s*=\s*([\d,\s]+)", re.I | re.M)
BARE_ID_FIELD = re.compile(r"\|\s*id\s*=\s*([\d,\s]+)", re.I | re.M)
ANY_ID_FIELD = re.compile(r"^\s*\|id(\d*)\s*=\s*(.+?)\s*$", re.I | re.M)
DROP_VERSION_FIELD = re.compile(r"^\s*\|dropversion(\d+)\s*=\s*(.+)$", re.I | re.M)


def _npc_infobox_source(wikitext: str) -> str:
    """Join every Infobox Monster/NPC template on a page into one block."""
    blocks = []
    for match in NPC_INFOBOX_START.finditer(wikitext):
        block = _read_balanced(wikitext, match.start() + 2)
        if block is not None:
            blocks.append("{{" + block + "}}")
    return "\n".join(blocks)


def parse_npc_ids(wikitext: str) -> List[int]:
    """Read every npc id declared in a page's monster infobox."""
    infobox = _npc_infobox_source(wikitext)
    if not infobox.strip():
        return []
    versioned = [
        npc_id
        for match in VERSIONED_ID_FIELD.finditer(infobox)
        for npc_id in _parse_id_list(match.group(2))
    ]
    if versioned:
        return sorted(set(versioned))
    bare = BARE_ID_FIELD.search(infobox)
    if not bare:
        return []
    return sorted(set(_parse_id_list(bare.group(1))))


def has_non_numeric_npc_id(wikitext: str) -> bool:
    """True when the infobox lists id fields but none are numeric.

    Pages for removed or unreleased npcs write ``|id1 = removed``, and have no
    npc to attach a drop table to.

    :param wikitext: Raw wikitext of the page.
    :return: True when the page should be skipped.
    """
    infobox = _npc_infobox_source(wikitext)
    if not infobox.strip():
        return False
    tokens = [
        token.strip()
        for match in ANY_ID_FIELD.finditer(infobox)
        for token in match.group(2).split(",")
        if token.strip()
    ]
    if not tokens:
        return False
    return not any(re.fullmatch(r"-?\d+", token) for token in tokens)


def _parse_id_list(raw: str) -> List[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]


def parse_npc_ids_by_drop_table(wikitext: str) -> Dict[str, List[int]]:
    """Map wiki drop-table section names (e.g. ``Drop table 1``) to npc ids.

    :param wikitext: Raw wikitext of the page.
    :return: Dictionary of drop version name to npc ids.
    """
    versions = {
        int(match.group(1)): match.group(2).strip()
        for match in DROP_VERSION_FIELD.finditer(wikitext)
    }
    if not versions:
        return {}

    ids_by_index = {
        int(match.group(1)): _parse_id_list(match.group(2))
        for match in VERSIONED_ID_FIELD.finditer(wikitext)
    }

    grouped: Dict[str, List[int]] = {}
    for index, table_name in versions.items():
        if index not in ids_by_index:
            continue
        grouped.setdefault(table_name, []).extend(ids_by_index[index])
    return {name: sorted(set(ids)) for name, ids in grouped.items()}


def parse_drop_version_names(wikitext: str) -> List[str]:
    """List the ``dropversionN`` names declared in a page's infobox."""
    return [
        match.group(2).strip()
        for match in DROP_VERSION_FIELD.finditer(wikitext)
        if match.group(2).strip()
    ]


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

DROP_TABLE_HEADING = re.compile(r"^==\s*(Drop table \d+|Drops)\s*==[ \t]*$", re.M)
# Fallback for pages that qualify the heading ("Drops (MVP/Solo)", "Members'
# worlds drops"). Only used when the strict heading matches nothing, so pages
# that already parse are untouched.
LOOSE_DROP_TABLE_HEADING = re.compile(
    r"^==\s*([^=\n]*\bdrops\b[^=\n]*?)\s*==[ \t]*$", re.I | re.M
)
LEVEL_2_HEADING = re.compile(r"^==[^=].*==", re.M)
DROP_VARIANT_HEADING = re.compile(r"^={3}(?!=)\s*(.+?)\s*={3}(?!=)[ \t]*$", re.M)
DROP_SUBSECTION_HEADING = re.compile(r"^={3,4}(?!=)\s*(.+?)\s*={3,4}(?!=)[ \t]*$", re.M)


def _parse_drop_table_sections(wikitext: str) -> Tuple[List[Tuple[str, str]], bool]:
    """Split a page into its drop table sections.

    :param wikitext: Raw wikitext of the page.
    :return: A (sections, matched the plain heading) tuple, where each section
        is a (heading, body) pair.
    """
    matches = list(DROP_TABLE_HEADING.finditer(wikitext))
    strict = bool(matches)
    if not matches:
        matches = list(LOOSE_DROP_TABLE_HEADING.finditer(wikitext))
    if not matches:
        return [], strict

    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            next_heading = LEVEL_2_HEADING.search(wikitext, start)
            end = next_heading.start() if next_heading else len(wikitext)
        sections.append((match.group(1).strip(), wikitext[start:end]))
    return sections, strict


def _split_drop_subsections(drops_section: str) -> List[Tuple[str, str]]:
    matches = list(DROP_SUBSECTION_HEADING.finditer(drops_section))
    if not matches:
        return [("", drops_section)]

    subsections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(drops_section)
        )
        subsections.append((match.group(1).strip(), drops_section[start:end]))
    return subsections


def _classify_section(heading: str) -> str:
    normalized = heading.lower()
    if "100%" in normalized or "always" in normalized:
        return SECTION_GUARANTEED
    if "tertiary" in normalized:
        return SECTION_TERTIARY
    return SECTION_MAIN


def is_standard_drop_subsection(heading: str) -> bool:
    """True when a level-3 heading names a drop category, not a drop variant."""
    normalized = heading.lower()
    if "100%" in normalized or "always" in normalized:
        return True
    if "weapon" in normalized and "armour" in normalized:
        return True
    if "rune" in normalized and "ammunition" in normalized:
        return True
    if (
        normalized == "herbs"
        or normalized.endswith(" herb")
        or normalized.endswith(" herbs")
    ):
        return True
    if "herb drop" in normalized:
        return True
    if normalized in ("materials", "coins", "other"):
        return True
    if "tertiary" in normalized:
        return True
    if "rare drop table" in normalized or "gem drop table" in normalized:
        return True
    if normalized == "seeds" or "seed drop" in normalized:
        return True
    return False


def _heading_matches_drop_version(heading: str, version: str) -> bool:
    heading = heading.lower()
    version = version.lower()
    return heading == version or version in heading or heading in version


def _matches_drop_version_variant(heading: str, drop_versions: List[str]) -> bool:
    if is_standard_drop_subsection(heading) or not drop_versions:
        return False
    if any(
        _heading_matches_drop_version(heading, version) for version in drop_versions
    ):
        return True

    tokens = [
        token.strip()
        for part in re.split(r"\s+and\s+", heading, flags=re.I)
        for token in part.split(",")
        if token.strip()
    ]
    return len(tokens) >= 2 and all(
        any(_heading_matches_drop_version(token, version) for version in drop_versions)
        for token in tokens
    )


def parse_drop_variants(drops_section: str, wikitext: str) -> List[Tuple[str, str]]:
    """Split a ``==Drops==`` section on infobox drop-version headings.

    Item category headings ("Weapons and armour") are not variants, so a page
    only splits when at least two headings name a declared ``dropversion``.

    :param drops_section: Wikitext of the drops section.
    :param wikitext: Raw wikitext of the whole page.
    :return: List of (variant name, section body) tuples.
    """
    drop_versions = parse_drop_version_names(wikitext)
    if not drop_versions:
        return [("", drops_section)]

    matches = [
        match
        for match in DROP_VARIANT_HEADING.finditer(drops_section)
        if _matches_drop_version_variant(match.group(1).strip(), drop_versions)
    ]
    if len(matches) < 2:
        return [("", drops_section)]

    variants = []
    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(drops_section)
        )
        variants.append((match.group(1).strip(), drops_section[start:end]))
    return variants


def npc_ids_for_drop_variant(
    wikitext: str, variant_name: str, fallback_npc_ids: List[int]
) -> List[int]:
    """Resolve the npc ids behind a drop variant heading.

    :param wikitext: Raw wikitext of the page.
    :param variant_name: The variant heading, e.g. ``Wilderness Slayer Cave``.
    :param fallback_npc_ids: Ids to use when the heading matches no drop version.
    :return: Sorted npc ids.
    """
    versions_to_ids = parse_npc_ids_by_drop_table(wikitext)
    if not versions_to_ids:
        return fallback_npc_ids

    tokens = [
        token.strip()
        for part in re.split(r"\s+and\s+", variant_name, flags=re.I)
        for token in part.split(",")
        if token.strip()
    ]

    matched = []
    for version_name, ids in versions_to_ids.items():
        if any(_heading_matches_drop_version(token, version_name) for token in tokens):
            matched.extend(ids)
    return sorted(set(matched)) or fallback_npc_ids


# ---------------------------------------------------------------------------
# Drop lines
# ---------------------------------------------------------------------------


def parse_wiki_quantity(raw_quantity: str) -> Tuple[str, bool]:
    """Strip a wiki ``(noted)`` quantity suffix.

    :param raw_quantity: The raw quantity field, e.g. ``5 (noted)``.
    :return: A (quantity, is noted) tuple.
    """
    is_noted = "(noted)" in raw_quantity.lower()
    quantity = re.sub(r"\s*\(noted\)", "", raw_quantity, flags=re.I).strip()
    return quantity or "1", is_noted


def _parse_drop_line(
    params: Dict[str, str],
    section: str,
    subsection: str,
    named_refs: Dict[str, str],
) -> Optional[ParsedDrop]:
    name = params.get("name", "").strip()
    if not name:
        return None

    name_notes = params.get("namenotes", "")
    rarity_notes = params.get("raritynotes", "")
    attached_notes = parse_inline_note_fields(
        name_notes, rarity_notes
    ) + _resolve_named_ref_links(name_notes, rarity_notes, named_refs)
    if _should_skip_f2p_drop(params, attached_notes):
        return None

    if name.lower() == "nothing":
        rarity = params.get("rarity", "").strip() or rarity_notes
        if not rarity.strip():
            return None
        return ParsedDrop(
            name=name,
            quantity="1",
            rarity=rarity,
            section=section,
            subsection=subsection,
            is_nothing=True,
        )

    quantity, is_noted = parse_wiki_quantity(params.get("quantity", "").strip() or "1")
    rarity = params.get("rarity", "").strip() or rarity_notes
    if not rarity.strip():
        return None

    relevant_notes = parse_inline_note_fields(name_notes, rarity_notes) + [
        note
        for note in _resolve_named_ref_links(name_notes, rarity_notes, named_refs)
        if _relevant_to_drop(name, note)
    ]
    notes = classify_notes(list(dict.fromkeys(relevant_notes)), name)

    if rarity.strip().lower() == "always" and section != SECTION_TERTIARY:
        section = SECTION_GUARANTEED

    return ParsedDrop(
        name=name,
        quantity=quantity,
        rarity=rarity,
        section=section,
        subsection=subsection,
        is_noted=is_noted,
        notes=notes.as_list(),
        clue_scroll_box=notes.has_clue_scroll_box(),
    )


def _parse_drops_from_body(body: str) -> List[ParsedDrop]:
    drops = []
    for heading, section_body in _split_drop_subsections(body):
        section = _classify_section(heading)
        named_refs = collect_named_footnotes(section_body)

        for _, params in extract_templates(section_body, "DropsLine"):
            drop = _parse_drop_line(params, section, heading, named_refs)
            if drop:
                drops.append(drop)

        for _, params in extract_templates(section_body, "DropsLineClue"):
            attached = parse_inline_note_fields(params.get("raritynotes", ""))
            if _should_skip_f2p_drop(params, attached):
                continue
            clue_type = params.get("type")
            rarity = params.get("rarity") or params.get("raritynotes")
            if not clue_type or not rarity:
                continue
            drop_name = f"Clue scroll ({clue_type})"
            notes = _clue_notes(
                drop_name=drop_name,
                clue_type=clue_type,
                rarity=rarity,
                note_override=params.get("noteoverride"),
                rarity_notes=params.get("raritynotes"),
            )
            drops.append(
                ParsedDrop(
                    name=drop_name,
                    quantity="1",
                    rarity=rarity,
                    section=section,
                    subsection=heading,
                    notes=notes.as_list(),
                    clue_scroll_box=notes.has_clue_scroll_box(),
                )
            )

    return drops


# ---------------------------------------------------------------------------
# Shared table accesses
# ---------------------------------------------------------------------------

# Templates that declare a roll into a shared table, in the order the Kotlin
# dumper resolved them: (shared table key, template names, subsection label).
SUBTABLE_TEMPLATES = [
    ("gem", ["GemDropTable"], "Gem drop table"),
    ("usefulHerb", ["UsefulHerbDropTableInfo", "UsefulHerbDropLines"], "Herbs"),
    ("combatHerb", ["CombatHerbDropTableInfo", "CombatHerbDropLines"], "Herbs"),
    (
        "seed",
        [
            "GeneralSeedDropTableInfo",
            "GeneralSeedDropTableIntro",
            "GeneralSeedDropTable",
            "GeneralSeedDropLines",
        ],
        "Seeds",
    ),
    ("rareSeed", ["RareSeedDropTableInfo", "RareSeedDropLines"], "Seeds"),
]

PROSE_ACCESS_PATTERNS = [
    ("herb", r"chance of rolling the herb drop table"),
    ("usefulHerb", r"chance of rolling the useful herb drop table"),
    ("combatHerb", r"chance of rolling the combat herb drop table"),
    ("gem", r"chance of rolling the gem drop table"),
    ("seed", r"chance of rolling the general seed drop table"),
    ("rareSeed", r"chance of rolling the rare seed drop table"),
    ("rareDrop", r"chance of rolling the rare drop table"),
    ("megaRare", r"chance of rolling the mega-?rare drop table"),
]

HERB_TABLE_ACCESS = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+chance of rolling (?:the\s+)?(?:\[\[)?(?:[^|\]]+\|)?herb drop table",
    re.I,
)
HERB_ROLL_VARIANT = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+chance of dropping ([123]) herbs?", re.I
)
HERB_QUANTITY_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def _herb_access_fraction(text: str) -> Optional[Tuple[int, int]]:
    match = HERB_TABLE_ACCESS.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return _first_fraction(text)


def _is_variable_herb_quantity(quantity: str) -> bool:
    match = HERB_QUANTITY_RANGE.match(quantity.strip())
    if not match:
        return False
    minimum, maximum = int(match.group(1)), int(match.group(2))
    return minimum >= 1 and maximum > minimum


def _parse_subtable_accesses(body: str) -> List[ParsedSubtableAccess]:
    accesses: List[ParsedSubtableAccess] = []

    def has_key(key: str) -> bool:
        return any(access.table_key == key for access in accesses)

    # A monster that rolls the herb table several times has no single shared
    # table to point at, so those accesses keep the empty table key.
    multi_roll_herbs = False
    for raw, params in extract_templates(body, "HerbDropTableInfo"):
        text = params.get("override") or raw
        fraction = _herb_access_fraction(text)
        if fraction:
            multi_roll_herbs = multi_roll_herbs or bool(HERB_ROLL_VARIANT.search(text))
            key = "" if multi_roll_herbs else "herb"
            accesses.append(
                ParsedSubtableAccess(key, fraction[0], fraction[1], "Herbs")
            )

    if not has_key("herb") and not has_key(""):
        for raw, params in extract_templates(body, "HerbDropLines"):
            chance = params.get("_0", "").strip() or raw.split("|")[0].strip()
            fraction = _herb_access_fraction(chance)
            if fraction:
                key = "" if _is_variable_herb_quantity(params.get("_1", "")) else "herb"
                accesses.append(
                    ParsedSubtableAccess(key, fraction[0], fraction[1], "Herbs")
                )
            break

    for raw, params in extract_templates(body, "RareDropTable"):
        rdt_chance = _first_fraction(params.get("_0", "")) or _first_fraction(raw)
        if rdt_chance:
            accesses.append(
                ParsedSubtableAccess(
                    "rareDrop", rdt_chance[0], rdt_chance[1], "Rare drop table"
                )
            )
        # The RDT template's second argument is the gem table access.
        gem_chance = _first_fraction(params.get("_1", ""))
        if gem_chance and not has_key("gem"):
            accesses.append(
                ParsedSubtableAccess(
                    "gem", gem_chance[0], gem_chance[1], "Gem drop table"
                )
            )

    for key, template_names, subsection in SUBTABLE_TEMPLATES:
        if has_key(key):
            continue
        for template_name in template_names:
            for raw, params in extract_templates(body, template_name):
                chance = params.get("_0", "").strip() or raw.split("|")[0].strip()
                fraction = _first_fraction(chance) or _first_fraction(raw)
                if fraction:
                    accesses.append(
                        ParsedSubtableAccess(key, fraction[0], fraction[1], subsection)
                    )
                    break
            if has_key(key):
                break

    # Pages that describe a shared table roll in prose instead of a template.
    for key, pattern in PROSE_ACCESS_PATTERNS:
        if has_key(key):
            continue
        for match in re.finditer(r"(\d+)\s*/\s*(\d+)\s+" + pattern, body, re.I):
            accesses.append(
                ParsedSubtableAccess(
                    key, int(match.group(1)), int(match.group(2)), SUBTABLE_LABELS[key]
                )
            )

    return accesses


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_all_drop_tables(wikitext: str) -> List[ParsedDropTable]:
    """Parse every drop table declared on a monster's wiki page.

    :param wikitext: Raw wikitext of the monster page.
    :return: One :class:`ParsedDropTable` per table/variant on the page.
    """
    sections, strict_headings = _parse_drop_table_sections(wikitext)
    if not sections:
        return []

    npc_ids_by_table = parse_npc_ids_by_drop_table(wikitext)
    fallback_npc_ids = parse_npc_ids(wikitext)
    page_vars = collect_page_vars(wikitext)

    tables = []
    for table_name, body in sections:
        if table_name.lower() == "drops":
            variants = parse_drop_variants(body, wikitext)
        else:
            variants = [("", body)]

        for variant_name, variant_body in variants:
            if variant_name:
                npc_ids = npc_ids_for_drop_variant(
                    wikitext, variant_name, fallback_npc_ids
                )
            elif table_name in npc_ids_by_table:
                npc_ids = npc_ids_by_table[table_name]
            elif len(sections) == 1 and len(variants) == 1:
                npc_ids = fallback_npc_ids
            elif not strict_headings:
                # Qualified headings ("Members' worlds drops", "Level 146
                # drops") describe the same npcs under different conditions,
                # so every table on the page belongs to all of them.
                npc_ids = fallback_npc_ids
            else:
                npc_ids = []

            drops = [
                _resolve_drop_rarity(drop, page_vars)
                for drop in _parse_drops_from_body(variant_body)
            ]
            tables.append(
                ParsedDropTable(
                    table_name=table_name,
                    drop_variant=variant_name,
                    drops=drops,
                    subtable_accesses=_parse_subtable_accesses(variant_body),
                    npc_ids=npc_ids,
                )
            )
    return tables


def _resolve_drop_rarity(drop: ParsedDrop, page_vars: Dict[str, str]) -> ParsedDrop:
    """Turn wiki arithmetic and word rarities into a plain rate, where possible."""
    resolved = resolve_rarity(drop.rarity, drop.name, page_vars)
    if resolved is None:
        return drop
    text, assumed = resolved
    if text == drop.rarity and not assumed:
        return drop
    drop.rarity = text
    drop.assumed_rarity = assumed
    return drop
