# Tasks: amazon-rufus clear login

## Implementation

- [x] Add `RufusBrowserStateStore.delete(country)`.
- [x] Add safe opscli-owned Chrome profile deletion in `BrowserAttachService`.
- [x] Add `RufusManager.logout(...)`.
- [x] Add `opscli amazon-rufus logout` command.
- [x] Keep CLI output free of cookies, headers, payload templates, storage state, and seed request data.

## Tests

- [x] Test store delete removes existing state.
- [x] Test store delete is idempotent when state is absent.
- [x] Test manager logout clears backend/MCP-readable state.
- [x] Test manager logout can skip browser profile deletion.
- [x] Test CLI logout passes arguments and returns safe summary.
- [x] Test safe profile deletion only removes opscli-owned Rufus profile directories.

## Verification

- [x] Run targeted Rufus tests.
- [x] Run targeted MCP Rufus tests if MCP behavior is touched.
- [x] Inspect diff for unrelated changes.
