# Tasks: amazon-rufus login recovery

## Specification

- [x] Confirm research, PRD, architecture, and UIUX documents.
- [x] Create Super Dev proposal and tasks after document confirmation.

## Tests

- [x] Add failing tests for `#nav-tools` login detection.
- [x] Add failing tests for `sso-state-main` / `at-main` Cookie-name login detection.
- [x] Add failing tests for i18n signed-out markers, including Spanish `identifícate`.

## Implementation

- [x] Replace fixed account-list selectors with `#nav-tools` text reading.
- [x] Treat `sso-state-main` / `at-main` Cookie names as login success.
- [x] Expand signed-out i18n markers without treating greetings like `Hola` as signed-out.
- [x] Update template and installed Skill docs to run `logout` before `watch-login`.
- [x] Keep sensitive Cookie values out of logs, reports, and responses.

## Verification

- [x] Run targeted Rufus browser/login tests.
- [x] Run targeted Skill documentation contract tests if docs assertions are touched.
- [x] Update `docs/change-log-pending.md`.
- [x] Inspect diff for unrelated changes.
