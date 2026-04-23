---
name: super-dev
description: Super Dev Codex App/Desktop plugin entry.
when_to_use: Use when the user wants to enter or resume the Super Dev pipeline inside Codex App/Desktop.
version: 2.4.0
---

# Super Dev for Codex Plugin

## Activation Contract

- If this plugin skill is invoked, Super Dev pipeline mode is already active.
- Do not explain the skill or summarize what it is before acting.
- Treat the Codex App/Desktop `/`-list entry `super-dev` as equivalent to Codex CLI `$super-dev`.
- If `AGENTS.md` or `.super-dev/SESSION_BRIEF.md` exists, read them before replying.

## Required First Reply

- State that Super Dev pipeline mode is active.
- State that the current phase is `research`, unless `.super-dev/SESSION_BRIEF.md` shows an active confirmation or revision gate.
- Promise to stop after research + PRD + architecture + UIUX for explicit confirmation before implementation.

## Required Workflow

1. Detect whether the work is `new`, `evolve`, `variant`, `patch`, or `resume`.
2. For `evolve`, `variant`, and `patch`, baseline the current repository first and write `output/*-baseline-audit.md` / `.json` before docs/spec.
3. Read `knowledge/` and `output/knowledge-cache/*-knowledge-bundle.json` when present.
4. Produce `output/*-research.md`.
5. Produce `output/*-prd.md`, `output/*-architecture.md`, and `output/*-uiux.md`.
6. Wait for explicit confirmation.
7. Only then create `.super-dev/changes/*/proposal.md` and `.super-dev/changes/*/tasks.md`.
8. Implement frontend first, then backend, then quality and delivery.

## Continuity Rules

- If the workflow is already waiting for docs confirmation, preview confirmation, UI revision, architecture revision, or quality revision, stay inside the current Super Dev gate.
- User replies like `修改`, `补充`, `继续改`, `确认`, `通过`, `继续` remain inside the current gate.
- Resume is a normal path: after reopening the host, continue from `.super-dev/SESSION_BRIEF.md`, workflow state, review state, and `output/*` rather than restarting from scratch.
- Do not silently fall back to ordinary chat.

## UI Rules

- Lock icon library, typography, design token system, component ecosystem, and page skeleton from `output/*-uiux.md` before any UI implementation.
- Do not use emoji as functional icons or placeholders.
- For non-conversational AI products, avoid Claude / ChatGPT-style chat shells unless the UI plan explicitly justifies them.

## Super Dev System Flow Contract
- SUPER_DEV_FLOW_CONTRACT_V1
- PHASE_CHAIN: research>docs>docs_confirm>spec>frontend>preview_confirm>backend>quality>delivery
- DOC_CONFIRM_GATE: required
- PREVIEW_CONFIRM_GATE: required
- HOST_PARITY: required
