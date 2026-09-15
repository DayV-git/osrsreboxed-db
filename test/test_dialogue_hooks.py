import json
from pathlib import Path

from scripts.dialogues import update
from scripts.dialogues.hooks import enrich_records, walk


def variants(value):
    return (
        {"standard-dialogue": value["steps"]} if "steps" in value else value["variants"]
    )


def record(name, raw):
    result = update.gameplay_npc(name, update.parse_npc(name, raw))
    result["source"] = {"page": "Transcript:" + name, "revision": 1}
    return result


def test_starts_identity_references_and_stable_ids():
    raw = """{{Transcript|quest}}
{{Transcript list|Cook (Lumbridge)}}
==Starting off==
* '''Cook:''' Help!
* {{tselect|Start the Cook's Assistant quest?}}
* {{topt|Yes.}}
** {{tact|Continues in [[Transcript:Cook's Assistant#Finishing up|the ending]]}}
* {{topt|No.}}
** {{tact|end}}
==Finishing up==
* {{tcond|If the player has the ingredients:}}
** '''Cook:''' Thank you.
"""
    npc = record("Cook (Lumbridge)", "==Standard dialogue==\n* '''Cook:''' Hello.")
    quest = record("Cook's Assistant", raw)
    npcs, quests = {"Cook (Lumbridge)": npc}, {"Cook's Assistant": quest}
    identity = {"Cook (Lumbridge)": {"wikitext": "{{Infobox NPC|name=Cook|id=4626}}"}}
    index = enrich_records(npcs, quests, identity, update.clean)
    assert npc["variants"]["standard-dialogue"][0]["npc"] == "Hello."
    assert len(index["4626"]) == 2
    assert quest["default"] == "starting-off"
    yes = next(
        n for n in walk(quest["variants"]["starting-off"]) if n.get("text") == "Yes."
    )
    assert yes["hook"] == "quest:cook-s-assistant:start"
    no = next(
        n for n in walk(quest["variants"]["starting-off"]) if n.get("text") == "No."
    )
    assert "hook" not in no
    ref = yes["steps"][0]
    assert ref["resolved"] and ref["variant"] == "finishing-up"
    assert quest["variants"]["finishing-up"][0]["condition_key"]
    modified = record(
        "Cook's Assistant",
        raw.replace("* '''Cook:''' Help!", "* '''Player:''' Hi.\n* '''Cook:''' Help!"),
    )
    enrich_records({}, {"Cook's Assistant": modified}, identity, update.clean)
    next_yes = next(
        n for n in walk(modified["variants"]["starting-off"]) if n.get("text") == "Yes."
    )
    assert next_yes["id"] == yes["id"]


def test_prequest_and_condition_openings_without_postquest_fallback():
    npc = record(
        "Veronica",
        "==Standard dialogue==\n===Pre-quest===\n* '''Veronica:''' Help.\n* {{tact|[[Ernest the Chicken]] is started.}}\n===Post-quest===\n* '''Veronica:''' Thanks.",
    )
    assert npc["default"] == "standard-dialogue-pre-quest"
    quests = {
        "Ernest the Chicken": record(
            "Ernest the Chicken", "==Starting out==\n* '''Veronica:''' Help."
        )
    }
    enrich_records({"Veronica": npc}, quests, {}, update.clean)
    assert (
        npc["variants"][npc["default"]][1]["hook"] == "quest:ernest-the-chicken:start"
    )
    conditional = record(
        "Romeo",
        "==Standard dialogue==\n* {{tcond|If not started:}}\n** {{tact|[[Transcript:Romeo & Juliet|quest]] dialogue shows}}",
    )
    assert conditional["default"] == "standard-dialogue"
    enrich_records({"Romeo": conditional}, {}, {}, update.clean)
    ref = conditional["variants"]["standard-dialogue"][0]["steps"][0]
    assert ref["target"] == "Transcript:Romeo & Juliet"
    assert not ref["resolved"] and not ref["page_available"]
    assert (
        record("Morgan", "==After Vampyre Slayer==\n* '''Morgan:''' Thanks.")["default"]
        is None
    )


def test_scope_short_names_and_leave_unresolved_navigation():
    npcs = {
        name: record(name, "==Standard dialogue==\n* '''Cook:''' Hi.\n* {{tact|above}}")
        for name in ["Cook (Lumbridge)", "Cook (servant)"]
    }
    pages = {
        name: {"wikitext": "{{Infobox NPC|name=Cook|id=" + str(i) + "}}"}
        for i, name in enumerate(npcs, 1)
    }
    index = enrich_records(npcs, {}, pages, update.clean)
    assert index["1"][0]["page"] == "Transcript:Cook (Lumbridge)"
    assert index["2"][0]["page"] == "Transcript:Cook (servant)"
    assert (
        npcs["Cook (Lumbridge)"]["variants"]["standard-dialogue"][1]["reference"]
        == "above"
    )


def test_fetch_dependencies_aliases_missing_and_refresh(tmp_path):
    from scripts.dialogues.fetch import download, transcript_targets

    assert transcript_targets("[[Transcript:X#Y|Z]]") == {"Transcript:X"}

    class Session:
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return self

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "query": {
                    "redirects": [{"from": "Old", "to": "New"}],
                    "pages": [
                        {
                            "title": "New",
                            "revisions": [
                                {"revid": 12, "slots": {"main": {"content": "Text"}}}
                            ],
                        },
                        {"title": "Missing", "missing": True},
                    ],
                }
            }

    session = Session()
    path = tmp_path / "pages.json"
    pages = download({"Old", "Missing"}, path, session)
    assert pages["Old"]["title"] == "New" and pages["Missing"]["missing"]
    download({"Old", "Missing"}, path, session)
    assert session.calls == 1
    download({"Old", "Missing"}, path, session, refresh=True)
    assert session.calls == 2


def test_starting_section_beats_talking_again():
    quest = record(
        "Vampyre Slayer",
        "==Starting off==\n* '''Morgan:''' Help!\n===Talking to Morgan again===\n* '''Morgan:''' Back again?",
    )
    assert quest["default"] == "starting-off"


def test_generated_exports():
    import os
    import pytest
    import jsonschema

    root = Path(
        os.environ.get("DIALOGUE_EXPORT_ROOT", Path(__file__).resolve().parents[1])
    )
    if not (root / "docs/npc-dialogues.json").exists():
        pytest.skip("Regenerate dialogue exports first")
    schema = json.loads((root / "data/schemas/schema-dialogues.json").read_text())
    dialogues = json.loads((root / "docs/npc-dialogues.json").read_text())
    minified = (root / "docs/npc-dialogues-minified.json").read_text()
    assert json.loads(minified) == dialogues
    assert minified == json.dumps(
        dialogues, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    records = {}
    jsonschema.Draft202012Validator(schema).validate(dialogues)
    for name, value in dialogues.items():
        records["Transcript:" + name] = value
        assert (
            "steps" in value
            or value["default"] is None
            or value["default"] in variants(value)
        )
        assert "entrypoint" not in value and "entrypoints" not in value
        ids = [
            n["id"]
            for steps in [
                *variants(value).values(),
                *value.get("branches", {}).values(),
            ]
            for n in walk(steps)
            if "id" in n
        ]
        assert len(ids) == len(set(ids)), name
    for record in records.values():
        for steps in [*variants(record).values(), *record.get("branches", {}).values()]:
            for node in walk(steps):
                assert "entrypoint" not in node
                if node.get("type") == "reference" and node.get("resolved"):
                    assert node["variant"] in variants(records[node["target"]])
    manifest = json.loads((root / "docs/dialogue-manifest.json").read_text())
    assert manifest.keys() == records.keys()
    jsonschema.validate(
        manifest,
        json.loads((root / "data/schemas/schema-dialogue-manifest.json").read_text()),
    )
    authoring = json.loads((root / "data/dialogues/authoring-index.json").read_text())
    jsonschema.validate(
        authoring,
        json.loads((root / "data/schemas/schema-dialogue-authoring.json").read_text()),
    )
    assert authoring.keys() == records.keys()
    assert len(set(manifest.values())) == len(manifest)
    for page, record in records.items():
        assert authoring[page]["sections"].keys() == variants(record).keys()
        for branch in record.get("branches", {}).values():
            assert not any(n.get("type") == "call" for n in walk(branch))
    for page, path in manifest.items():
        assert json.loads((root / "docs" / path).read_text()) == records[page]
        for steps in variants(records[page]).values():
            for node in walk(steps):
                if node.get("type") == "call":
                    assert node["branch"] in records[page]["branches"]
    index = json.loads((root / "docs/npc-dialogue-index.json").read_text())
    jsonschema.validate(
        index,
        json.loads((root / "data/schemas/schema-npc-dialogue-index.json").read_text()),
    )
    for entries in index.values():
        for entry in entries:
            assert entry["page"] in records
            assert set(entry["variants"]) <= variants(records[entry["page"]]).keys()
    for name in [
        "Cook's Assistant",
        "Sheep Shearer",
        "Imp Catcher",
        "Vampyre Slayer",
        "The Restless Ghost",
        "Doric's Quest",
    ]:
        quest = dialogues[name]
        assert quest["default"] is not None, name
        assert any(
            n.get("hook", "").endswith(":start")
            for n in walk(quest["variants"][quest["default"]])
        ), name
    assert any(e["page"] == "Transcript:Cook's Assistant" for e in index["4626"])


def test_participant_page_display_names():
    from scripts.dialogues.fetch import participant_pages

    assert participant_pages(
        "{{Transcript list|Cook (Lumbridge)|Bob (cat){{!}}Bob|[[Other NPC|Alias]]|noplayer}}"
    ) == ["Bob (cat)", "Cook (Lumbridge)", "Other NPC"]


def test_quest_in_title_is_not_stripped_from_hook():
    quest = record(
        "Doric's Quest",
        "==Starting off==\n* {{tselect|Start Doric's Quest?}}\n* {{topt|Yes.}}\n** {{tact|end}}",
    )
    enrich_records({}, {"Doric's Quest": quest}, {}, update.clean)
    assert (
        quest["variants"]["starting-off"][0]["options"][0]["hook"]
        == "quest:doric-s-quest:start"
    )


def test_compaction_expands_losslessly_and_keeps_hook_identity():
    import copy
    from scripts.dialogues.compact import compact_record
    from scripts.dialogues.compact import runtime_id

    speech = [{"npc": "A sufficiently long repeated line. " * 20}, {"type": "end"}]
    original = record("X", "==Standard dialogue==\n* '''X:''' Hello.")
    original["variants"]["standard-dialogue"] = [
        {
            "type": "choice",
            "id": "choice",
            "options": [
                {
                    "text": "A",
                    "id": "a",
                    "hook": "quest:x:start",
                    "steps": copy.deepcopy(speech),
                },
                {
                    "text": "B",
                    "id": "b",
                    "condition": "If ready",
                    "condition_key": "old",
                    "steps": copy.deepcopy(speech),
                },
            ],
        },
        {"type": "action", "id": "effect", "action": "give", "text": "coin"},
    ]
    result = copy.deepcopy(original)
    authoring = compact_record(result)
    assert "source" not in result and authoring["source"] == original["source"]
    assert "entrypoint" not in result
    choice = result["steps"][0]
    assert "id" not in choice and "id" not in choice["options"][0]
    assert choice["options"][0]["hook"] == "quest:x:start"
    assert choice["options"][1]["id"] == runtime_id("b")
    assert "condition_key" not in choice["options"][1]
    assert len(result["branches"]) == 1
    for option in choice["options"]:
        assert result["branches"][option["steps"][0]["branch"]] == speech
    assert result["steps"][1]["action"] == "give"


def test_dedup_does_not_merge_different_effects_or_conditions():
    from scripts.dialogues.compact import deduplicate

    record = {
        "variants": {
            "a": [{"type": "action", "id": "a", "text": "x" * 300}],
            "b": [{"type": "action", "id": "b", "text": "x" * 300}],
        }
    }
    deduplicate(record)
    assert "branches" not in record


def test_runtime_id_collisions_block_publication(monkeypatch):
    from scripts.dialogues import compact

    monkeypatch.setattr(compact, "runtime_id", lambda value: "sameid")
    value = {
        "variants": {
            "v": [{"type": "action", "id": "a"}, {"type": "action", "id": "b"}]
        },
        "sections": {"v": ["v"]},
    }
    import pytest

    with pytest.raises(ValueError, match="collision"):
        compact.compact_record(value)


def test_terminal_ends_preserve_all_choice_outcomes():
    import copy
    from scripts.dialogues.compact import remove_terminal_ends

    def traces(steps):
        if not steps:
            return {()}
        first, *rest = steps
        if first.get("type") == "end":
            return {()}
        if first.get("type") == "choice":
            return set().union(
                *(traces(option.get("steps", []) + rest) for option in first["options"])
            )
        if first.get("type") == "condition":
            return traces(first.get("steps", []) + rest) | traces(rest)
        return {
            (first.get("npc", first.get("action")), *tail)
            for tail in traces(first.get("steps", []) + rest)
        }

    choice = {
        "type": "choice",
        "options": [
            {"text": "Leave", "steps": [{"npc": "Bye"}, {"type": "end"}]},
            {"text": "Stay", "steps": [{"npc": "Hello"}]},
        ],
    }
    for original in [
        [choice],
        [choice, {"action": "reward"}],
        [{"type": "condition", "steps": [choice]}, {"action": "reward"}],
        [{"type": "condition", "steps": [choice]}],
        [{"npc": "Bye"}, {"type": "end"}],
    ]:
        result = copy.deepcopy(original)
        remove_terminal_ends(result)
        assert traces(result) == traces(original)
    tail = copy.deepcopy(choice)
    remove_terminal_ends([tail])
    assert tail["options"][0]["steps"] == [{"npc": "Bye"}]
    guarded = [copy.deepcopy(choice), {"action": "reward"}]
    remove_terminal_ends(guarded)
    assert guarded[0]["options"][0]["steps"][-1] == {"type": "end"}
    marked = [{"type": "end", "reason": "members"}]
    remove_terminal_ends(marked)
    assert marked == [{"type": "end", "reason": "members"}]


def test_flatten_only_selected_single_standard_variant():
    from scripts.dialogues.compact import compact_record

    for heading, expected_flat in [("Standard dialogue", True), ("After quest", False)]:
        value = record(
            "NPC", "==" + heading + "==\n* '''NPC:''' Hello.\n* {{tact|end}}"
        )
        enrich_records({"NPC": value}, {}, {}, update.clean)
        compact_record(value)
        assert ("steps" in value) == expected_flat
        if expected_flat:
            assert value["steps"] == [{"npc": "Hello."}]
            assert "variants" not in value and "default" not in value
        else:
            assert value["default"] is None
