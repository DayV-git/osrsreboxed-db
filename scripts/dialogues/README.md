# NPC and quest dialogue exports

Build with `python -m scripts.dialogues.update`. The collector fetches the wiki's
**NPC dialogue** and **Quest transcript** categories, follows explicit transcript
links, and fetches NPC identity pages named by transcripts. Cached revisions are
reused; `--refresh` fetches them again. `--offline` rebuilds only from cached sources.
A failed download does not publish a partial gameplay export. Explicitly missing
wiki pages remain cached and unresolved; use `--refresh` to retry them.

## Files

- `docs/npc-dialogues.json`: all NPC and quest/reference conversations, keyed by transcript title without `Transcript:`.
- `docs/npc-dialogues-minified.json`: identical aggregate data without formatting whitespace or a trailing newline; Unicode stays literal UTF-8 and dialogue text is preserved.
- `docs/npc-dialogue-index.json`: NPC ID -> candidate transcript pages and variants.
- `data/dialogues/wiki-pages.json`, `quest-pages.json`, `npc-pages.json`: source wikitext and revision IDs.
- `data/dialogues/authoring-index.json`: source revisions, participant identities and section descriptions, keyed by transcript page.
- `docs/dialogue-manifest.json`: transcript page -> one independently loadable file under `docs/dialogues/`.
- `data/dialogues/review-issues.json`: missing content, unresolved navigation and parser diagnostics.
- `data/dialogues/inferred-actions.txt`: inferred and unimplemented actions for review.

The NPC-ID index uses the existing wiki infobox ID extractor. Quest participants
come from `Transcript list`, and their spoken names are matched only within those
explicit participant pages. NPCs sharing a short name are never globally merged.
An absent ID mapping is unresolved identity, not permission to guess a name match.
The index lists candidates, not a quest-state-aware routing decision.

## Record shapes and natural endings

When the only variant is `standard-dialogue` and it is the selected default,
the record uses `steps` directly:

```json
{"steps": [{"npc": "Hello."}]}
```

Otherwise it keeps `variants` and `default`. A sole post-quest
variant with `default: null` is not flattened. Both shapes can have `branches`.
The flat form still represents the implicit variant `standard-dialogue` in the
NPC-ID and authoring indexes.
Resolve a variant as follows:

```js
const steps = record.steps !== undefined
  ? (variant === 'standard-dialogue' ? record.steps : undefined)
  : record.variants[variant];
```

A bare `end` is omitted only at a provable tail position with no subsequent local
or enclosing steps. The runner closes when the root conversation queue is exhausted.
Explicit ends still terminate the entire conversation, including parent continuations.
Ends with reasons (e.g. members-only), hooks or other metadata remain explicit.
Pruning happens before sharing branches, so an end needed at any call site is
not removed by treating a shared branch as a standalone conversation.
Variants are root/transfer entrypoints, not subroutines with implicit return tails;
only `call` nodes return to a caller's remaining steps.

## Hooking a quest

For Cook (NPC 4626), look up `npc-dialogue-index.json["4626"]`. One candidate is
`Transcript:Cook's Assistant`, variant `starting-off`. Load that from
`npc-dialogues.json["Cook's Assistant"].variants["starting-off"]`.
Its Yes option carries:

```json
{"hook": "quest:cook-s-assistant:start", "quest": "Cook's Assistant"}
```

Bind that hook to the quest plugin's acceptance handler. Run it **after the player
selects the option and its condition passes, before playing its steps**. The
handler checks requirements and sets the persisted stage. Rejection stops the
branch. It must be idempotent: the NPC and quest transcripts can describe the
same acceptance, and an explicit start action may repeat it.

Standalone explicit `X is started` actions become `action: "quest_start"` with
the same hook. These prose-derived markers retain `action_source: "text"` for
review. Acceptance hooks are emitted only for exact Yes choices under explicit
`Start ...?` prompts naming a collected quest. We do not infer acceptance from
arbitrary speech or automatically grant items/XP.

Bind entry conditions by transcript page and variant name; no separate entrypoint
ID is needed. For a condition node or conditional option, use
`condition:<node ID>`. This key is derived, not repeated in the JSON.
Condition prose remains in the runtime data. Unbound conditions block the branch;
selecting a default does not make its entry condition automatically true.

IDs remain on conditions, effects and references. Menus, unconditional options,
ordinary speech and end nodes have none; named quest hooks need no extra ID.
IDs are 6-character URL-safe hashes of the previous
source-addressed identity, so unrelated insertions still do not rename branches.
Editing a node's text, renaming a section or inserting identical siblings can
change affected IDs. Semantic `quest:...:start` hooks remain unchanged.

The authoring index retains source revisions, original section paths, participants
and NPC identities. It is not needed during playback; use the NPC-ID index for
routing. This compact format replaces the earlier long IDs and stored condition
keys; update node-level bindings when migrating. IDs are scoped to their conversation (branch IDs use their local branch table).
The exporter rejects collisions rather than silently aliasing nodes. Existing
16-character node bindings must migrate; named quest hooks are unchanged.
No quest stage rules are inferred.

## Shared branches and selective loading

Byte-for-byte identical terminal step lists can be stored once in a record's
`branches` table. A step `{"type":"call","branch":"<ID>"}` means: play that
local branch **then resume the remaining caller steps**. It is not a wiki jump.
Shared branches cannot call other branches, and their conditions/effects/IDs must
match exactly. Calls inherit the same player and speaker context as inline steps.
Do not treat a call as a dialogue end or skip it. Tiny repeats stay inline when a
reference would cost more bytes. Unresolved wiki navigation is unchanged.

For selective loading, fetch the manifest once, then only the selected page:

```js
const manifest = await fetch('/dialogue-manifest.json').then(r => r.json());
const file = manifest["Transcript:Cook's Assistant"];
const dialogue = await fetch('/' + file).then(r => r.json());
const opening = dialogue.steps ?? dialogue.variants[dialogue.default];
```

The server can similarly read the manifest and load only the selected JSON file.
NPC-ID index entries identify candidate pages and variants; the plugin selects the
right one from quest state. Explicit cross-page references use the same manifest.
Each shard is identical to its aggregate record and includes its own shared branches.
The readable and minified aggregate exports are available for bulk consumers.
These and the shards are alternative delivery formats; publishing all duplicates
storage. Every build writes `npc-dialogues-minified.json` beside the readable
aggregate, including when `--out` selects another directory. The generator removes
stale hash-named shards on rebuild.

## References and defaults

Explicit transcript links retain `type: "reference"`, `target` (page), `section`,
`page_available` and `resolved`. An unambiguous section match also gets the target’s `variant` name.
A page-only reference is **not** resolved to its default: e.g. an NPC's Yes branch
must not replay the quest's opening menu. A plugin can handle that reference node
by ID and route to the appropriate stage. Unresolved `above`, `previous`, `other`,
`continue` etc. remain blocking `jump` nodes; their targets are never guessed.

Defaults recognise `Pre-quest`, starting sections and conditional openings.
Post-quest-only records remain `default: null`. Default selection is a heading
heuristic, never a substitute for quest-state checks. Canonical variant keys are
preserved, rather than renaming the selected one to `standard`.

## Runner compatibility

This extends the earlier NPC-only format. Consumers must use each record's
`default` value rather than hardcode `standard`, and support explicit speakers
(`type: "line"`, `speaker`, `text`) in multi-NPC quest conversations. Scoped NPC
self-speech is still `{"npc":"..."}`, player speech `{"player":"..."}`.
Choices/random alternatives have nested `options` and `steps`. Message, missing,
unavailable, condition and reference nodes must not silently disappear.

`open_shop.target` is an exact key in `shops-items-by-shop.json`; `open_interface`
is not a shop ID. `receive`, `give`, teleport and other effects may still carry
prose instead of structured game IDs/amounts. Bind effects by node ID in the quest
plugin; don't execute prose. `action_source: "text"` identifies inferred actions.

Schemas: `data/schemas/schema-dialogues.json`, `schema-npc-dialogue-index.json`,
`schema-dialogue-manifest.json` and `schema-dialogue-authoring.json`.
Python record types: `osrsreboxed.dialogues.DialogueRecord` and `FlatDialogueRecord`.
Run `python -m pytest test/test_dialogues_export.py test/test_dialogue_hooks.py`.

Source: https://oldschool.runescape.wiki/ — game dialogue copyright Jagex;
wiki content CC BY-NC-SA 3.0, additional terms at
https://meta.weirdgloop.org/w/Licensing. Retain `docs/npcs-dialogues.LICENSE`
when redistributing the dialogue data.
