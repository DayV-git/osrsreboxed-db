"""Export compact gameplay dialogue for every page in the NPC dialogue category.

Run with --offline to rebuild from data/dialogues/wiki-pages.json without fetching.
"""

import argparse
import collections
import json
import re
from pathlib import Path

import mwparserfromhell as mw

import config
from scripts.dialogues.fetch import CACHE, fetch, save


def clean(raw):
    """Remove presentation markup; retain unfamiliar templates verbatim."""
    code = mw.parse(str(raw))
    for template in code.filter_templates(recursive=False):
        name = str(template.name).strip().lower()
        if name in ("colour", "color") and template.has(2):
            code.replace(template, clean(template.get(2).value))
        elif name == "overhead" and template.has(1):
            code.replace(template, clean(template.get(1).value))
        elif name == "sic":
            code.replace(template, "")
    # Keep unrecognised templates through strip_code rather than dropping data.
    saved = []
    for template in code.filter_templates(recursive=False):
        saved.append(str(template))
        code.replace(template, f"\ue000{len(saved)-1}\ue001")
    text = code.strip_code().strip()
    for i, template in enumerate(saved):
        text = text.replace(f"\ue000{i}\ue001", template)
    return text


# Gameplay slugs inferred from wiki prose rather than template parameters. This is
# a guess: every step matched here is marked action_source="text" so a consumer can
# choose to trust only the template-derived slugs. First pattern wins; a named group
# "t" supplies the target. Prose targets are wiki display strings, not interface ids.
CONDITION_PROSE = re.compile(r"^\(?If\s+(?:the\s+player|you|they)\b", re.I)

PROSE_ACTIONS = [
    (
        "open_interface",
        re.compile(
            r"^\(?(?:the\s+|game\s+opens\s+the\s+)?(?P<t>.+?)\s+"
            r"(?:interface|menu|screen)\s+opens\b",
            re.I,
        ),
    ),
    (
        "open_interface",
        re.compile(r"^\(?(?:game\s+)?opens\s+(?:the\s+)?(?P<t>.+?)[.)]*$", re.I),
    ),
    ("open_interface", re.compile(r"^\(?(?P<t>[A-Z][^.)]*?)\s+opens\b")),
    (
        "receive",
        re.compile(r"\b(?:player|you)\s+(?:receives?|is\s+given|are\s+given)\b", re.I),
    ),
    (
        "teleport",
        re.compile(
            r"\btelep(?:orts?|orted)\s+the\s+player\b"
            r"|\btransports?\s+the\s+player\b"
            r"|\bplayer\b[^.]{0,40}?\b(?:is|are|gets?)\s+"
            r"(?:teleported|transported|brought|taken|moved)\b",
            re.I,
        ),
    ),
    (
        "heal",
        re.compile(
            r"\bheals?\b[^.]{0,30}\b(?:player|you)\b|\bplayer\s+is\s+healed\b", re.I
        ),
    ),
    (
        "emote",
        re.compile(
            r"\bperforms?\s+the\b.*\bemote\b"
            r"|\b(?:bows|dances|cheers|waves|claps|shrugs|nods|laughs)\b",
            re.I,
        ),
    ),
]


TARGET_NOUN = re.compile(r"\s+(?:interface|menu|screen|panel)$", re.I)
TARGET_NOISE = {"interface", "menu", "screen", "panel", "tab", "game", "shop"}


def infer_action(text):
    """Guess a gameplay slug from an action's prose; empty when nothing matches."""
    if not text:
        return {}
    if CONDITION_PROSE.match(text):
        return dict(type="condition", action_source="text")
    for slug, pattern in PROSE_ACTIONS:
        match = pattern.search(text)
        if not match:
            continue
        inferred = dict(action=slug, action_source="text")
        target = TARGET_NOUN.sub("", match.groupdict().get("t") or "")
        target = target.strip(" .)\"'")
        # A bare noun ("Interface", "Game") names nothing; keep the prose instead.
        if target and target.lower() not in TARGET_NOISE:
            inferred["target"] = target
        return inferred
    return {}


def parse_step(raw, issues, line):
    speech = re.fullmatch(r"'''(.+?):'''\s*(.*)", raw)
    if speech:
        text = clean(speech[2])
        node = dict(type="line", speaker=clean(speech[1]), text=text)
        if "{{overhead" in raw.lower():
            node["display"] = "overhead"
        if "{{" in text:
            issues.append(
                dict(line=line, reason="Unrecognised inline template", raw=raw)
            )
        return node
    templates = mw.parse(raw).filter_templates(recursive=False)
    if len(templates) == 1 and str(templates[0]) == raw:
        t = templates[0]
        name = str(t.name).strip().lower()
        args = {str(p.name).strip(): clean(p.value) for p in t.params}
        text = args.get("1", "")
        if name == "topt":
            node = dict(type="option", text=text)
            if "cond" in args:
                node["condition"] = args["cond"]
            return node
        if name in ("tcond", "tselect", "tbox", "mes", "qact", "tinput"):
            node = dict(
                type={
                    "tcond": "condition",
                    "tselect": "menu",
                    "tbox": "message",
                    "mes": "message",
                    "qact": "action",
                    "tinput": "input",
                }[name],
                text=text,
            )
            if "pic" in args:
                node["image"] = args["pic"]
            if node["type"] == "action":
                node.update(infer_action(text))
            return node
        if name == "trandom":
            return dict(type="random_marker")
        if name in ("tmissing", "transcript missing"):
            issues.append(dict(line=line, reason="Transcript missing"))
            return dict(type="missing")
        if name == "tact":
            if text == "end":
                return dict(type="end")
            # A free-to-play branch stops here; the conversation is members-only.
            if text == "members":
                return dict(type="end", reason="members")
            if re.fullmatch(r"above|below|previous\d*|initial|other|continues?", text):
                issues.append(
                    dict(line=line, reason="Unresolved dialogue reference", raw=raw)
                )
                return dict(type="jump", target=None, reference=text)
            # opens2 is the unlinked spelling of opens; the two never co-occur.
            if "opens" in args or "opens2" in args:
                return dict(
                    type="action",
                    action="open_interface",
                    target=args.get("opens") or args.get("opens2"),
                )
            if "receives" in args:
                return dict(type="action", action="receive", text=args["receives"])
            if "gives" in args:
                return dict(type="action", action="give", text=args["gives"])
            node = dict(type="action", text=text, parameters=args)
            node.update(infer_action(text))
            return node
    issues.append(dict(line=line, reason="Unrecognised markup retained", raw=raw))
    return dict(type="unparsed", raw=raw)


def group_options(nodes, random_options=False):
    """Group sibling alternatives, keeping their nested bodies and order."""
    result = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if "steps" in node and node["type"] != "option":
            node["steps"] = group_options(node["steps"])
        if node["type"] in ("menu", "random_marker", "option"):
            kind = (
                "random"
                if random_options or node["type"] == "random_marker"
                else "choice"
            )
            group = dict(type=kind, options=[])
            if node["type"] != "option":
                if node.get("text"):
                    group["prompt"] = node["text"]
                i += 1
            while i < len(nodes) and nodes[i]["type"] == "option":
                option = nodes[i]
                group["options"].append(
                    {k: v for k, v in option.items() if k != "type"}
                )
                option_body = group["options"][-1]
                option_body["steps"] = group_options(option.get("steps", []))
                i += 1
            result.append(group)
        else:
            result.append(node)
            i += 1
    return result


def select_default(variants):
    """Choose a baseline conversation by headings, never by NPC name."""
    ordinary = {
        "standard dialogue",
        "normal dialogue",
        "dialogue",
        "talking",
        "talking to",
    }
    repeats = {"subsequent dialogue", "repeat dialogue", "subsequent conversation"}
    initial = {"initial dialogue", "initial conversation", "first conversation"}
    candidates = []
    for key, variant in variants.items():
        steps = variant["steps"]
        if not steps or steps[0]["type"] not in ("line", "choice", "random"):
            continue
        *parents, label = [part.strip().casefold() for part in variant["section_path"]]
        if any(parent not in ordinary | initial for parent in parents):
            continue
        if label in ordinary:
            rank = 0
        elif label in repeats:
            rank = 1
        elif label in initial:
            rank = 2
        elif label == "unsectioned":
            rank = 3
        elif re.match(r"(?:(?:standard|normal) dialogue\s+)?before\b", label):
            rank = 4
        elif re.match(
            r"(?:without\b|if (?:the player )?(?:isn't|is not) (?:carrying|wearing)\b)",
            label,
        ):
            rank = 5
        else:
            continue
        candidates.append((rank, key))
    # ponytail: heading heuristic, ties use wiki order; explicit gameplay conditions need structured data.
    return (
        min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None
    )


def parse_npc(name, raw):
    variants, issues, headings = {}, [], []
    stack = []
    current = None
    raw = re.sub(
        r"<!--.*?-->", lambda match: "\n" * match[0].count("\n"), raw, flags=re.S
    )
    for number, original in enumerate(raw.splitlines(), 1):
        line = original.strip()
        if not line:
            continue
        heading = re.fullmatch(r"(={2,6})\s*(.*?)\s*\1", line)
        if heading:
            level = len(heading[1])
            headings = [(n, h) for n, h in headings if n < level]
            headings.append((level, clean(heading[2])))
            current = None
            stack = []
            continue
        if line.lower().startswith("{{transcript|"):
            continue
        if (
            line.lower().startswith("{{incomplete")
            and mw.parse(line).filter_templates()
        ):
            t = mw.parse(line).filter_templates()[0]
            issues.append(
                dict(
                    line=number,
                    reason="Incomplete source",
                    text=clean(t.get(1).value) if t.has(1) else "",
                )
            )
            continue
        if current is None:
            path = [h for _, h in headings] or ["Unsectioned"]
            key = re.sub(r"[^a-z0-9]+", "-", "/".join(path).lower()).strip("-")
            base = key
            suffix = 2
            while key in variants:
                key = f"{base}-{suffix}"
                suffix += 1
            current = dict(label=path[-1], section_path=path, steps=[])
            variants[key] = current
        bullet = re.fullmatch(r"(\*+)\s*(.*)", line)
        depth, body = (len(bullet[1]), bullet[2]) if bullet else (1, line)
        node = parse_step(body, issues, number)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1].setdefault("steps", []).append(node)
        else:
            current["steps"].append(node)
        stack.append((depth, node))
    for variant in variants.values():
        is_oracle = name == "Oracle" and variant["section_path"] == [
            "Standard dialogue"
        ]
        variant["steps"] = group_options(variant["steps"], random_options=is_oracle)
        if is_oracle:
            variant["notes"] = [
                "Curated: numbered alternatives are random dialogue, not player choices; probabilities unknown."
            ]
    return dict(
        default=select_default(variants), variants=variants, review_issues=issues
    )


def gameplay_step(node, name):
    """Drop editorial/source data while retaining dialogue flow and gameplay requirements."""
    if node.get("type") == "line" and node.get("speaker") in (name, "Player"):
        result = {"npc" if node["speaker"] == name else "player": node["text"]}
    elif node.get("type") == "unparsed":
        result = {"type": "unavailable"}
    else:
        result = {
            key: value
            for key, value in node.items()
            if key
            in (
                "type",
                "speaker",
                "text",
                "condition",
                "action",
                "target",
                "reference",
                "reason",
                "action_source",
                "prompt",
            )
            and value is not None
        }
    if node.get("steps"):
        result["steps"] = [gameplay_step(child, name) for child in node["steps"]]
    if "options" in node:
        result["options"] = [gameplay_step(option, name) for option in node["options"]]
    if result.get("prompt", "").lower() in ("select an option", "select an option."):
        result.pop("prompt")
    return result


def gameplay_npc(name, parsed):
    default = parsed["default"]
    variants = {
        key: [gameplay_step(step, name) for step in variant["steps"]]
        for key, variant in parsed["variants"].items()
    }
    if default and "standard" not in variants:
        variants = {
            "standard" if key == default else key: steps
            for key, steps in variants.items()
        }
        default = "standard"
    return {"default": default, "variants": variants}


SHOPS = "shops-items-by-shop.json"
# A wiki link and a shop page title disagree on decoration, not on identity.
SHOP_DECORATION = re.compile(r"\[\[|\]\]|\s*\(shop\)\s*$", re.I)


def normalise_shop(name):
    """Fold a target and a shop page title onto one key, or "" when there is none."""
    name = re.sub(r"\{\{!\}\}.*$", "", name)  # pipe-trick display half
    name = SHOP_DECORATION.sub("", name).strip().strip(".").casefold()
    return re.sub(r"\s+", " ", re.sub(r"^the\s+", "", name))


def shop_keys(name):
    """Spellings a dialogue may use for one shop, loosest last; "" is never a key."""
    key = normalise_shop(name)
    # Tried strictest first, so a target spelled exactly like a shop still resolves
    # when a near-identical sibling would make the looser keys ambiguous. The wiki
    # and the shop title disagree on hyphens and spacing (Black Market Goods vs
    # Black-market Goods); dropping punctuation entirely settles that.
    spellings = (name, key, re.sub(r"[^a-z0-9]", "", key))
    return [k for k in dict.fromkeys(spellings) if k]


def shop_index():
    """Every shop spelling to its canonical key. Empty when the shops dump is unbuilt."""
    path = config.DOCS_PATH / SHOPS
    if not path.exists():
        print(f"{path} not built; every interface stays open_interface", flush=True)
        return {}
    names = collections.defaultdict(set)
    for shop in json.loads(path.read_text()):
        for key in shop_keys(shop):
            names[key].add(shop)
    # Two shops folding onto one key (quest-state variants) cannot be told apart.
    return {key: value.pop() for key, value in names.items() if len(value) == 1}


def resolve_shops(npcs, index):
    """Retag interfaces naming a known shop so consumers can join on the shops dump."""
    resolved = 0

    def walk(node):
        nonlocal resolved
        if isinstance(node, dict):
            target = (
                node.get("target") if node.get("action") == "open_interface" else None
            )
            shop = next(
                (index[key] for key in shop_keys(target or "") if key in index), None
            )
            if shop:
                node["action"] = "open_shop"
                node["target"] = shop
                resolved += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(npcs)
    return resolved


def action_report(npcs):
    """Every prose-inferred action plus the prose left unslugged, for human review."""
    inferred, unmatched = (
        collections.defaultdict(collections.Counter),
        collections.Counter(),
    )
    owners = collections.defaultdict(set)

    def walk(name, node):
        if isinstance(node, dict):
            if node.get("action_source") == "text":
                slug = node.get("action") or node["type"]
                key = (node.get("target", ""), node.get("text", ""))
                inferred[slug][key] += 1
                owners[slug, key].add(name)
            elif node.get("type") == "action" and "action" not in node:
                unmatched[node.get("text", "")] += 1
                owners["", node.get("text", "")].add(name)
            for value in node.values():
                walk(name, value)
        elif isinstance(node, list):
            for item in node:
                walk(name, item)

    for name, npc in npcs.items():
        walk(name, npc)

    def examples(key):
        names = sorted(owners[key])
        shown = ", ".join(names[:3])
        return f"{shown}{', +%d more' % (len(names) - 3) if len(names) > 3 else ''}"

    total = sum(sum(c.values()) for c in inferred.values())
    lines = [
        "Inferred dialogue actions",
        "=" * 72,
        "Generated by scripts/dialogues/update.py -- do not edit by hand.",
        "",
        "Every step in the INFERRED sections was slugged by matching a regex against",
        "the wiki's prose, not by reading a template parameter, and carries",
        'action_source="text" in docs/npcs-dialogues.json. Read each line and check',
        "the slug (and target) describe what the prose says. Wrong ones mean a",
        "pattern in PROSE_ACTIONS is too loose; the UNMATCHED section is the other",
        "half of the review -- anything there that clearly is one of the slugs means",
        "a pattern is too tight.",
        "",
        "Template-derived slugs (opens/opens2/receives/gives) are exact and are not",
        "listed here.",
        "",
        f"{total} inferred steps, {sum(unmatched.values())} left as prose.",
        "",
    ]
    for slug in sorted(inferred):
        counts = inferred[slug]
        lines.append("")
        lines.append(
            f"INFERRED {slug}  ({sum(counts.values())} steps, {len(counts)} distinct)"
        )
        lines.append("-" * 72)
        for (target, text), count in counts.most_common():
            lines.append(f"  [{count:>3}] {text}")
            if target:
                lines.append(f"        target: {target}")
            lines.append(f"        npcs:   {examples((slug, (target, text)))}")
    lines.append("")
    lines.append("")
    lines.append(
        f"UNMATCHED  ({sum(unmatched.values())} steps, {len(unmatched)} distinct) "
        "-- still prose, no action key"
    )
    lines.append("-" * 72)
    for text, count in unmatched.most_common():
        lines.append(f"  [{count:>3}] {text}")
        lines.append(f"        npcs:   {examples(('', text))}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="Use the saved wiki sources."
    )
    parser.add_argument(
        "--out", type=Path, default=config.DOCS_PATH / "npcs-dialogues.json"
    )
    args = parser.parse_args()
    pages = json.loads(CACHE.read_text()) if args.offline else fetch()
    npcs, issues = {}, {}
    for title, page in sorted(pages.items()):
        name = title.removeprefix("Transcript:")
        parsed = parse_npc(name, page["wikitext"])
        npcs[name] = gameplay_npc(name, parsed)
        if parsed["review_issues"]:
            issues[title] = parsed["review_issues"]
    resolved = resolve_shops(npcs, shop_index())
    save(args.out, npcs)
    save(config.DATA_PATH / "dialogues" / "review-issues.json", issues)
    report = config.DATA_PATH / "dialogues" / "inferred-actions.txt"
    report.write_text(action_report(npcs))
    print(
        f"Wrote {len(npcs)} NPCs, {sum(len(n['variants']) for n in npcs.values())} variants, "
        f"{sum(n['default'] is not None for n in npcs.values())} selected defaults to {args.out}"
    )
    print(f"Resolved {resolved} interfaces to a named shop")


if __name__ == "__main__":
    main()
