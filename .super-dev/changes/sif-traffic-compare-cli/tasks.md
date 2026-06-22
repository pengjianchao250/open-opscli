# Tasks: Sif Traffic and Multi-Product Compare CLI

## 1. Governance

- [x] Create research, PRD, architecture, and UIUX docs.
- [x] Confirm endpoint enum values and site mapping requirements.
- [x] Implement and verify.

## 2. Shared Sif Platform

- [x] Add generic Sif run/export models.
- [x] Add site normalization aliases.
- [x] Add feature-level output directory resolution.
- [x] Add generic GET/POST XLSX download helpers with sanitized request metadata.
- [x] Add Referer/header support for traffic structure download.

## 3. Traffic

- [x] Add traffic scenario payload builders.
- [x] Add `SifTrafficProvider`.
- [x] Save 3 XLSX files for structure, reverse traffic keywords, and multi natural position keywords.
- [x] Write stable `params.json`, `raw.json`, and `result.json`.

## 4. Compare

- [x] Add compare scenario payload builders.
- [x] Add `SifCompareProvider`.
- [x] Save compare sales XLSX.
- [x] Save compare traffic structure XLSX files for `showType=1` and `showType=2`.
- [x] Save compare keyword XLSX files for `listType=1` and `listType=2`.
- [x] Write stable `params.json`, `raw.json`, and `result.json`.

## 5. CLI and Skill

- [x] Extend `opscli sif features`.
- [x] Route `opscli sif run 查流量` and aliases.
- [x] Route `opscli sif run 多产品对比`.
- [x] Add `--time-piece-type`, `--time-piece-value`, `--sections`, and `--my-asin`.
- [x] Create unified `ops-sif` Skill template.
- [x] Migrate Sif sales Skill guidance into `ops-sif`.

## 6. Tests

- [x] Add traffic payload/provider tests.
- [x] Add compare payload/provider tests.
- [x] Add site normalization tests.
- [x] Add CLI routing tests.
- [x] Run focused Sif pytest.
