"""Source-addressed dialogue nodes and explicit plugin handoff points.

No quest state is inferred or executed here. The consumer binds condition keys
and quest events; unresolved references remain blocking nodes.
"""

import collections
import hashlib
import json
import re

import mwparserfromhell as mw

from scripts.shops.shop_owners import npc_ids_from_wikitext


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def token(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("steps", []))
        yield from walk(node.get("options", []))


def identity(name, page, clean):
    raw = page.get("wikitext", "")
    ids = npc_ids_from_wikitext(raw) if raw else []
    names = {name}
    for template in mw.parse(raw).filter_templates():
        if str(template.name).strip().casefold() not in (
            "infobox npc",
            "infobox monster",
            "infobox pet",
        ):
            continue
        for param in template.params:
            if re.fullmatch(r"name\d*", str(param.name).strip(), re.I):
                names.add(clean(param.value))
    return ids, names


def annotate(nodes, parent, quest_names):
    counts = collections.Counter()
    for node in nodes:
        # Exclude child bodies: adding a line to an option does not rename its
        # branch or descendants. Duplicate identical siblings use a local suffix.
        own = {k: v for k, v in node.items() if k not in ("steps", "options")}
        key = token([parent, own])
        counts[key] += 1
        node["id"] = f"{parent.split('/node:')[0]}/node:{key}" + (
            f"-{counts[key]}" if counts[key] > 1 else ""
        )
        condition = node.get("condition") or (
            node.get("text") if node.get("type") == "condition" else None
        )
        if condition:
            node["condition_key"] = f"condition:{token([parent, condition])}"
        if node.get("type") == "action":
            start = re.fullmatch(r"(.+?) is started\.?", node.get("text", ""), re.I)
            if start and slug(start[1]) in quest_names:
                node.update(
                    action="quest_start",
                    quest=quest_names[slug(start[1])],
                    hook=f"quest:{slug(start[1])}:start",
                    action_source="text",
                )
        annotate(node.get("steps", []), node["id"], quest_names)
        annotate(node.get("options", []), node["id"], quest_names)
        prompt = re.fullmatch(r"Start (.+?)\?", node.get("prompt", ""), re.I)
        if prompt:
            # Try the literal title first: Quest and The can be part of a name.
            title = prompt[1]
            candidates = [title, re.sub(r"^the\s+", "", title, flags=re.I)]
            candidates += [
                re.sub(r"\s+quest$", "", value, flags=re.I) for value in candidates
            ]
            key = next(
                (slug(value) for value in candidates if slug(value) in quest_names),
                None,
            )
            if key:
                for option in node.get("options", []):
                    if option.get("text", "").strip().casefold().rstrip(".! ") == "yes":
                        option["hook"] = f"quest:{key}:start"
                        option["quest"] = quest_names[key]


def enrich_records(npcs, quests, npc_pages, clean):
    identities = {name: identity(name, page, clean) for name, page in npc_pages.items()}
    all_records = {
        "Transcript:" + name: record
        for group in (npcs, quests)
        for name, record in group.items()
    }
    quest_names = {slug(name): name for name in quests}
    index = collections.defaultdict(list)
    for page, record in all_records.items():
        name = page.removeprefix("Transcript:")
        is_npc = name in npcs
        ids, names = identities.get(name, ([], {name})) if is_npc else ([], set())
        if is_npc:
            record["npc_ids"] = ids
        for variant, steps in record["variants"].items():
            for node in walk(steps):
                if node.get("type") == "line" and node.get("speaker") in names:
                    text = node.pop("text")
                    node.pop("type")
                    node.pop("speaker")
                    node["npc"] = text
            annotate(steps, f"{page}#{variant}", quest_names)
        if is_npc:
            for npc_id in ids:
                index[str(npc_id)].append(
                    {"page": page, "variants": list(record["variants"])}
                )
        else:
            # Participants come from explicit Transcript list wiki-page links,
            # never a global short-name match (multiple NPCs can be called Cook).
            for participant in record.get("participants", []):
                participant_ids, aliases = identities.get(participant, ([], set()))
                variants = [
                    key
                    for key, steps in record["variants"].items()
                    if any(n.get("speaker") in aliases for n in walk(steps))
                ]
                if variants:
                    for npc_id in participant_ids:
                        index[str(npc_id)].append({"page": page, "variants": variants})
    for record in all_records.values():
        for steps in record["variants"].values():
            for node in walk(steps):
                if node.get("type") != "reference":
                    continue
                if not node["target"]:
                    node["target"] = record["source"]["page"]
                target = all_records.get(node["target"])
                section = node.get("section", "")
                matches = (
                    []
                    if target is None
                    else [
                        key
                        for key, section_path in target["sections"].items()
                        if slug(section) in (key, slug(section_path[-1]))
                    ]
                )
                if section and len(matches) == 1:
                    node["variant"] = matches[0]
                # A page-only reference is NOT a license to replay its opening.
                node["resolved"] = "variant" in node
                node["page_available"] = target is not None
    return dict(sorted(index.items(), key=lambda item: int(item[0])))
