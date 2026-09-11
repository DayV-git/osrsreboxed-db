"""Export compact gameplay dialogue for every page in the NPC dialogue category.

Run with --offline to rebuild from data/dialogues/wiki-pages.json without fetching.
"""

import argparse
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
            return node
        if name == "trandom":
            return dict(type="random_marker")
        if name in ("tmissing", "transcript missing"):
            issues.append(dict(line=line, reason="Transcript missing"))
            return dict(type="missing")
        if name == "tact":
            if text == "end":
                return dict(type="end")
            if re.fullmatch(r"above|below|previous\d*|initial", text):
                issues.append(
                    dict(line=line, reason="Unresolved dialogue reference", raw=raw)
                )
                return dict(type="jump", target=None, reference=text)
            if "opens" in args:
                return dict(
                    type="action", action="open_interface", target=args["opens"]
                )
            if "receives" in args:
                return dict(type="action", action="receive", text=args["receives"])
            return dict(type="action", text=text, parameters=args)
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
    save(args.out, npcs)
    save(config.DATA_PATH / "dialogues" / "review-issues.json", issues)
    print(
        f"Wrote {len(npcs)} NPCs, {sum(len(n['variants']) for n in npcs.values())} variants, "
        f"{sum(n['default'] is not None for n in npcs.values())} selected defaults to {args.out}"
    )


if __name__ == "__main__":
    main()
