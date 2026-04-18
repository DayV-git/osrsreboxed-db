# GitHub Copilot instructions — OSRSReboxed (osrsbox)

## Project purpose

Build and maintain **Old School RuneScape** open datasets: **items**, **monsters**, and **prayers**, exposed as JSON under `docs/` and as the **`osrsreboxed`** Python package in `osrsreboxed/`.

## Directory responsibilities

- **`config.py`** — canonical `Path` constants (`PROJECT_ROOT_PATH`, `DATA_*`, `BUILDERS_*`, `SCRIPTS_*`, etc.); import these instead of hard-coding strings.
- **`builders/items/`**, **`builders/monsters/`** — regenerate JSON per entity (`builder.py`). Shared flow: `builders/base_builder.py`, logging under `logs/` via `builders/run_log.py`.
- **`scripts/`** — automation to populate `data/` (cache extraction, wiki fetch/parsing, shop updates, icon tooling, batch `update/` helpers).
- **`data/`** — inputs and schemas (`data/schemas/`). `data/cache/` is not shipped in full; scripts expect it locally when working with cache dumps.
- **`docs/`** — build artefacts (per-id JSON, combined files). Prefer changing generators, not bulk hand-editing.
- **`osrsreboxed/`** — user-facing API (`items_api`, `monsters_api`, `prayers_api`); keep property names aligned with JSON.
- **`test/`** — pytest coverage for DB shape and invariants.

## Fork-specific rules

- **No monster `drops` arrays** in this fork; do not restore upstream drop logic by default.
- Monster schema extensions include **`elemental_weakness_type`**, **`elemental_weakness_percent`**, and **`defence_ranged_light` / `defence_ranged_standard` / `defence_ranged_heavy`**.
- **Shops**: implement or fix in **`scripts/shops/`** with data under **`data/shops/`**.

## Coding expectations for new changes

- Match existing module structure, headers, and use **`pathlib.Path`** + **`logging`** like peer files.
- Use **Black**-style formatting.
- When altering exported JSON: update **`data/schemas/`**, relevant **`test/`** assertions, and **`osrsreboxed`** dataclasses in the same change set where possible.
- For HTTP/wiki tasks, honour **`config.custom_agent`**.

## What not to do

- One-off edits across many `docs/**/*.json` files when a script or builder change is the durable fix.
- Unrelated refactors or new dependencies without clear pipeline need and manifest updates (`pyproject.toml`).
