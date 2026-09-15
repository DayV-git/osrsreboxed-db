"""Compact runtime records without changing dialogue content or control flow."""

import base64
import collections
import json

from scripts.dialogues.fetch import save
from scripts.dialogues.hooks import token


def runtime_id(value):
    return base64.urlsafe_b64encode(bytes.fromhex(token(value))).decode()[:6]


def compact_record(record):
    authoring = {
        key: record.pop(key)
        for key in ("source", "participants", "npc_ids")
        if key in record
    }
    authoring["sections"] = record.pop("sections")

    def visit(node):
        if isinstance(node, list):
            for value in node:
                visit(value)
        elif isinstance(node, dict):
            for value in list(node.values()):
                visit(value)
            if "id" in node:
                if (
                    "npc" in node
                    or "player" in node
                    or node.get("type") in ("line", "end")
                ) and not any(key in node for key in ("hook", "condition")):
                    del node["id"]
                elif (
                    node.get("type") in ("choice", "random") or "type" not in node
                ) and "condition" not in node:
                    del node["id"]
                else:
                    node["id"] = runtime_id(node["id"])
            node.pop("condition_key", None)

    visit(record["variants"])
    ids = []
    from scripts.dialogues.hooks import walk

    ids.extend(
        n["id"]
        for steps in record["variants"].values()
        for n in walk(steps)
        if "id" in n
    )
    if len(ids) != len(set(ids)):
        raise ValueError(
            "Runtime ID collision; increase runtime_id width before publishing"
        )
    for steps in record["variants"].values():
        remove_terminal_ends(steps)
    deduplicate(record)
    if record["default"] == "standard-dialogue" and list(record["variants"]) == [
        "standard-dialogue"
    ]:
        record["steps"] = record.pop("variants")["standard-dialogue"]
        del record["default"]
    return authoring


def remove_terminal_ends(steps, continuation=False):
    """Only bare ends at a tail position can become natural conversation EOF."""
    for index, node in enumerate(steps):
        follows = continuation or index < len(steps) - 1
        # Unknown node types may have different continuation rules: leave them.
        if (
            "npc" in node
            or "player" in node
            or node.get("type") in (None, "line", "choice", "random", "condition")
        ):
            if "steps" in node:
                remove_terminal_ends(node["steps"], follows)
            for option in node.get("options", []):
                if "steps" in option:
                    remove_terminal_ends(
                        option["steps"], follows or bool(node.get("steps"))
                    )
    if not continuation and steps and steps[-1] == {"type": "end"}:
        steps.pop()


def deduplicate(record):
    # Only share byte-for-byte identical terminal step lists. In particular, never
    # merge branches with different hook IDs, conditions, speakers or effects.
    lists = []

    def collect(steps):
        lists.append(steps)
        for node in steps:
            if "steps" in node:
                collect(node["steps"])
            for option in node.get("options", []):
                if "steps" in option:
                    collect(option["steps"])

    for steps in record["variants"].values():
        collect(steps)
    candidates = collections.defaultdict(list)
    for steps in lists:
        if steps and all(not n.get("steps") and not n.get("options") for n in steps):
            key = json.dumps(
                steps, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            candidates[key].append(steps)
    branches = {}
    for key, copies in candidates.items():
        branch = runtime_id(key)
        if branch in branches:
            raise ValueError("Shared branch ID collision")
        call = {"type": "call", "branch": branch}
        # Include the branch-table key and calls; tiny repeats stay inline.
        if (
            len(copies) < 2
            or (len(copies) - 1) * len(key.encode())
            <= len(copies) * len(json.dumps(call)) + len(branch) + 16
        ):
            continue
        branches[branch] = list(copies[0])
        for steps in copies:
            steps[:] = [dict(call)]
    if branches:
        record["branches"] = branches


def write_split(directory, groups):
    manifest = {}
    for group in groups:
        for name, record in group.items():
            page = "Transcript:" + name
            if page in manifest:
                raise ValueError(f"Duplicate dialogue page: {page}")
            relative = f"dialogues/{token(page)}.json"
            save(directory / relative, record)
            manifest[page] = relative
    save(directory / "dialogue-manifest.json", manifest)
    # Remove only stale generated shards, never arbitrary neighbouring files.
    live = {directory / path for path in manifest.values()}
    for path in (directory / "dialogues").glob("*.json"):
        if (
            len(path.stem) == 16
            and all(c in "0123456789abcdef" for c in path.stem)
            and path not in live
        ):
            path.unlink()
