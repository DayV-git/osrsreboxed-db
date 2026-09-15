# NPC dialogue export

`docs/npcs-dialogues.json` contains every transcript in the wiki's NPC dialogue
category, keyed by its exact wiki NPC name. The server uses exact cache-name
matching, so disambiguated page names are not silently merged.

```sh
python -m scripts.dialogues.update
python -m scripts.dialogues.update --offline
```

The first command discovers all category members and downloads uncached pages
in batches. The second rebuilds entirely offline. To refresh existing pages,
remove their entries from `data/dialogues/wiki-pages.json` (or remove that cache
file to refresh everything). Downloads are checkpointed; failed requests do not
replace the gameplay export with partial results.

Select `data[name].variants[data[name].default]`. Variants are arrays of steps.
`{"npc":"Hello."}` and `{"player":"Hi."}` are spoken lines. Choices retain
`type: "choice"`, their `options` and nested `steps`; random alternatives use
`type: "random"`. Conditions, action descriptions, unresolved jumps and missing
content remain explicit, so the runner can stop safely where gameplay logic has
not been implemented. Empty `steps` and standard choice prompts are omitted.

`{{tact}}` control-flow keywords are transcript navigation, not gameplay, and
become `type: "jump"` with the keyword as `reference` (`above`, `below`,
`previous`, `initial`, `other`, `continue`, `continues`). Targets are not
resolved. `members` ends a free-to-play branch as `{"type":"end","reason":
"members"}`. Steps that do carry gameplay are slugged with an `action` key:
`open_interface` with a `target` (from `opens` or its unlinked `opens2`
spelling), `receive` and `give` with the item `text`. Everything else stays an
`action` with the wiki's prose in `text` and no `action` key — a runner must
treat those as unimplemented rather than guess.

An `open_interface` whose target names a shop in `docs/shops-items-by-shop.json`
becomes `open_shop` with the dump's exact key as `target`, so a consumer can index
straight into the shops export. Targets are tried strictest first: the exact shop
title, then wiki-link decoration folded away (`[[...]]`, the `{{!}}` pipe-trick
display half, a trailing `(shop)` or full stop, a leading `The`, case), then all
punctuation dropped, which settles hyphen and spacing disagreements such as
`Black Market Goods` against `Black-market Goods.`. It never guesses: a spelling
two shops share resolves to neither, and an unmatched target stays
`open_interface`. Trying the exact title first means a target spelled like a shop
still resolves when a near-identical sibling would make the looser keys ambiguous. This reads the shops export, so build shops first;
when that file is absent the step is skipped and every interface stays
`open_interface`.

Some slugs are inferred by matching regexes against that prose instead of reading
a template parameter (`open_interface`, `receive`, `teleport`, `heal`, `emote`,
and prose conditionals retyped to `condition`). Those steps carry
`action_source: "text"`; steps without the key were derived from template markup
and are exact. A consumer that cannot tolerate a wrong guess should ignore the
marked ones. Inferred `target` values come from wiki display strings, so they name
an interface no more precisely than `opens` does — neither is an interface id.
Every inferred step and every unslugged prose step is listed for review in
`data/dialogues/inferred-actions.txt`, rewritten on each run; a wrong slug there
means a pattern in `PROSE_ACTIONS` needs tightening.

Defaults are selected by headings, with no NPC-name overrides: standard/normal
conversation first, then subsequent, initial, unsectioned, pre-quest ("Before..."),
and no-item ("Without..." / "If the player isn't carrying/wearing...") dialogue.
Only sections with a spoken line, choice or random opening qualify. Nested
sections must have ordinary/initial conversation parents, excluding special
contexts such as overhead speech, item use and quest stages. Ties use wiki order;
no qualifying candidate means null. This is a baseline selection heuristic,
not an evaluation of the player's quest state. The chosen variant is named
`standard`; alternatives retain keys derived from wiki headings.

The gameplay file omits raw source, review diagnostics, revision metadata,
repeated NPC speaker names, section labels/paths, images and editorial notes.
Raw sources and revision IDs live in `data/dialogues/wiki-pages.json`;
`data/dialogues/review-issues.json` holds parser diagnostics. Unknown markup becomes
an unavailable step instead of disappearing from a branch. HTML comments are
excluded. Oracle's numbered alternatives are curated as random dialogue; other
pages use explicit wiki random markers. Random probabilities are not provided.

This exports the category pages themselves. Missing dialogue and links to
separately maintained quest transcripts are not reconstructed. The wiki is a
human-authored source; a complete category download does not mean every branch
is implemented by the game server.

Source: https://oldschool.runescape.wiki/w/Category:NPC_dialogue
Game dialogue copyright Jagex. Wiki content CC BY-NC-SA 3.0, additional terms:
https://meta.weirdgloop.org/w/Licensing
