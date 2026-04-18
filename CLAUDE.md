# Claude / agent instructions — OSRSReboxed (osrsbox)

## What this repo is

A **Python** data pipeline and **`osrsreboxed`** package that produces **OSRS** item, monster, and prayer databases as **JSON** under `docs/`, with supporting data under `data/` and automation under `scripts/` and `builders/`.

## Layout (authoritative paths in `config.py`)

- **`builders/items/`**, **`builders/monsters/`** — main regeneration entry points (`builder.py`); common orchestration in `builders/base_builder.py`; run logging via `builders/run_log.py` → `logs/`.
- **`scripts/`** — domain scripts: `cache`, `wiki`, `items`, `monsters`, `shops`, `icons`, `update` (prepare or refresh inputs in `data/`).
- **`data/`** — source JSON, wiki dumps, schemas (`data/schemas/`), icons; `data/cache/` is local/large.
- **`docs/`** — generated static API JSON; treat as build output unless the task is explicitly a one-off fix with a follow-up generator change.
- **`osrsreboxed/`** — PyPI API (dataclasses); must match exported JSON contracts.
- **`test/`** — pytest; extend when export shape or validation rules change.
- **`validator.py`** — Cerberus extensions used in validation.

## Fork constraints (read before editing monsters or docs)

- **Monster `drops` are removed** in this fork; do not add drop parsing or drop arrays unless the user explicitly wants that scope.
- Monsters use **`elemental_weakness_*`** and split ranged defence: **`defence_ranged_light`**, **`defence_ranged_standard`**, **`defence_ranged_heavy`**.
- **Shops** data is maintained via **`scripts/shops/`** and **`data/shops/`** (not a `builders/shops` package).

## How to implement new work

1. Decide the correct layer: **`scripts/`** (ingest/transform), **`builders/`** (assemble per-entity JSON), **`osrsreboxed/`** (consumer types), or **`test/`** / **`data/schemas/`** (contracts).
2. Follow neighbouring modules: **`pathlib`**, **`logging`**, existing copyright/GPL header pattern where used, and **`BaseBuilder`** patterns for item/monster builders.
3. Run **Black**-compatible formatting.
4. If JSON fields change: update **schemas**, **tests**, and **`osrsreboxed`** dataclasses together.
5. For wiki/network code, reuse **`config.custom_agent`**.

## Avoid

- Large manual edits under `docs/**` that should be regenerated.
- Drive-by unrelated refactors outside the requested scope.
