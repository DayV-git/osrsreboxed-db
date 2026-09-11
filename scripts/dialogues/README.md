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
