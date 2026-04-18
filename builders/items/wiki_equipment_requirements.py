"""
Wiki-derived equipment requirements parsing and comparison for the item build.

Compares levels parsed from item page wikitext (equip/wield/wear sentences) against
`equipment.requirements` from the infobox build, and builds structured discrepancy
records for downstream updates (e.g. items-skill-requirements.json).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

_WIKITEXT_SKILL_PATTERN = re.compile(r"(\d+)\s+(\[\[)?([A-Za-z ]+?)(\]\])?(?=\s|$)")


def parse_equip_requirements_from_wikitext(
    wikitext: Union[str, List[Any], None],
) -> Dict[str, int]:
    """Extract skill -> level requirements from prose before ==Combat stats==.

    Mirrors the historical ``BuildItem.extract_requirements`` behaviour.
    """
    if not wikitext:
        return {}
    if isinstance(wikitext, list):
        wikitext = wikitext[-1]
    if not isinstance(wikitext, str):
        return {}

    changes_index = wikitext.find("==Combat stats==")
    if changes_index != -1:
        wikitext = wikitext[:changes_index]

    allowed_skills = {
        "attack",
        "defence",
        "strength",
        "magic",
        "hitpoints",
        "ranged",
        "prayer",
        "agility",
    }
    reqs: Dict[str, int] = {}
    sentences = [s.strip() for s in wikitext.split(".") if s.strip()]
    for sentence in sentences:
        lower_sentence = sentence.lower()
        if (
            "to wield" not in lower_sentence
            and "to equip" not in lower_sentence
            and "to wear" not in lower_sentence
        ):
            continue
        for match in _WIKITEXT_SKILL_PATTERN.finditer(sentence):
            level = match.group(1)
            skill = match.group(3)
            skill_key = skill.strip().lower()
            num_start = match.start(1)
            num_end = match.end(1)
            before_num = sentence[num_start - 1] if num_start > 0 else ""
            after_num = sentence[num_end] if num_end < len(sentence) else ""
            if (
                before_num
                and not before_num.isspace()
                and before_num.isprintable()
                and before_num not in [",", "."]
            ) or (
                after_num
                and not after_num.isspace()
                and after_num.isprintable()
                and after_num not in [",", "."]
            ):
                continue
            if skill_key == "hitpoints":
                before = sentence[: match.start()].lower()
                if "heal" in before or "restor" in before:
                    continue
            if skill_key in allowed_skills:
                level_int = int(level)
                if 2 <= level_int <= 99:
                    reqs[skill_key] = level_int
    return reqs


def drop_trivial_level_one(reqs: Optional[Dict[str, int]]) -> Dict[str, int]:
    """Ignore level-1 requirements (noise for comparison)."""
    if not reqs:
        return {}
    return {k: v for k, v in reqs.items() if v != 1}


def merge_proposed_requirements(
    database_requirements: Dict[str, int], wiki_requirements: Dict[str, int]
) -> Dict[str, int]:
    """Merge DB + wiki; wiki values override for the same key."""
    merged = dict(database_requirements)
    merged.update(wiki_requirements)
    return merged


def wiki_vs_database_requirements_meaningful_mismatch(
    wiki_requirements: Dict[str, int], database_requirements: Dict[str, int]
) -> bool:
    """True if wiki-derived requirements disagree with DB in a non-trivial way."""
    if wiki_requirements == database_requirements:
        return False
    for k, v in wiki_requirements.items():
        if k not in database_requirements or database_requirements[k] != v:
            return True
    return False


def build_discrepancy_record(
    *,
    item_id: int,
    name: str,
    wiki_name: Optional[str],
    wikitext_lookup: Optional[str],
    wiki_requirements: Dict[str, int],
    database_requirements: Dict[str, int],
) -> Dict[str, Any]:
    """Single structured row for the requirements audit JSON."""
    proposed = merge_proposed_requirements(database_requirements, wiki_requirements)
    return {
        "id": item_id,
        "name": name,
        "wiki_name": wiki_name,
        "wikitext_lookup": wikitext_lookup,
        "wiki_requirements": wiki_requirements,
        "database_requirements": database_requirements,
        "proposed_requirements": proposed,
    }
