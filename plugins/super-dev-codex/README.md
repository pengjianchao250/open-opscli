# Super Dev Codex Plugin

This is an optional local Codex plugin scaffold for repositories that want a richer Codex App/Desktop surface than `AGENTS.md + Skills` alone.

It does not replace the official Super Dev Codex integration surfaces:

- `AGENTS.md`
- `.agents/skills/super-dev/SKILL.md`
- `CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`, only when explicitly enabling `--with-user-surfaces`)
- `~/.agents/skills/super-dev/SKILL.md`

Use this plugin scaffold as an advanced Codex App/Desktop enhancement when you want the repository to expose a repo-local plugin entry in addition to the official AGENTS/Skills model.

Plugin root:

- `.codex-plugin/plugin.json`
- `skills/super-dev/SKILL.md`
- optional legacy compatibility alias files may still exist for cleanup or migration, but the public skill name remains `super-dev`.

Marketplace entry:

- `.agents/plugins/marketplace.json`

The plugin skill should behave exactly like the main Codex Super Dev workflow:

- App/Desktop slash list entry: `super-dev`
- App/Desktop SEEAI slash list entry: `super-dev-seeai`
- CLI explicit skill mention: `$super-dev`
- CLI explicit SEEAI skill mention: `$super-dev-seeai`
- AGENTS fallback: `super-dev: <需求描述>`
- Existing-project work (`evolve` / `variant` / `patch`) must baseline the repository before docs/spec.
- Resume is a first-class default path: continue with `super-dev: 继续当前流程` or `super-dev-run: resume` when the host does not support slash.

## Super Dev System Flow Contract
- SUPER_DEV_FLOW_CONTRACT_V1
- PHASE_CHAIN: research>docs>docs_confirm>spec>frontend>preview_confirm>backend>quality>delivery
- DOC_CONFIRM_GATE: required
- PREVIEW_CONFIRM_GATE: required
- HOST_PARITY: required
