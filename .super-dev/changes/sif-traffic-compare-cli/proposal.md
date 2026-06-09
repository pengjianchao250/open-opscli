# Proposal: Sif 查流量与多产品对比 CLI

## Goal

Extend the existing platform-level Sif CLI:

```bash
opscli sif run 查流量 --asin B01NBNDC1T --site US
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF --site 美国
```

The new implementation must reuse the current Sif authentication and output pattern, while adding Sif traffic and multi-ASIN compare exports.

## Scope

- Keep `opscli sif` as the only user-facing entry.
- Add `查流量` / `查流量词` aliases for single-ASIN traffic exports.
- Add `多产品对比` for multi-ASIN compare exports.
- Add site normalization for country names and marketplace aliases.
- Add feature-level default output directories under `~/.config/opscli/sif/<feature>/runs`.
- Save platform XLSX downloads plus `params.json`, `raw.json`, and `result.json`.
- Create a unified `ops-sif` Skill covering Sif sales, traffic, and compare.
- Add focused tests for payloads, downloads, routing, output schema, and sensitive-data hygiene.

## Non-Goals

- No MCP implementation in this change.
- No backend write.
- No XLSX table parsing or business diagnosis in the first version.
- No Playwright click automation.
- No hardcoded Sif credentials.

## Decisions

- `showType=1` downloads compare traffic words.
- `showType=2` downloads compare traffic score.
- `listType=1` downloads key traffic keywords.
- `listType=2` downloads key ad keywords.
- Compare sales uses POST `/api/updown/boughtByAsin/download` with multi-ASIN payload.
- Traffic structure GET download must include page context headers, at least `Referer`.
- `--sections` is supported and defaults to all sections.
