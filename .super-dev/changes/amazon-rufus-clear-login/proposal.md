# Proposal: amazon-rufus clear login

## Summary

Add a local Rufus logout command:

```text
opscli amazon-rufus logout <COUNTRY>
```

The command clears the country-specific Rufus encrypted browser state that both CLI and MCP use, and optionally clears the opscli-owned Chrome debugging profile.

## Problem

Rufus CLI can save Amazon state through `save-state`, `cookie save`, `curl save`, and `watch-login`, but it has no first-class command to clear that state. Users currently have to know internal file paths to remove credentials, and MCP keeps reading the same encrypted state on later `amazon_rufus_get` calls.

## Goals

1. Clear `RufusBrowserStateStore` state for one country.
2. Make the next MCP `amazon_rufus_get` unable to read old Rufus credentials.
3. Clear the opscli-owned Chrome profile by default.
4. Return only a safe summary.
5. Keep the implementation scoped to existing Rufus service boundaries.

## Non-Goals

1. Do not clear the user's normal Chrome profile.
2. Do not clear ops auth credentials, JWT, or MCP API keys.
3. Do not add an MCP destructive logout tool in this change.
4. Do not add `--all` country cleanup in this change.

## Design

Add:

```text
RufusBrowserStateStore.delete(country) -> bool
BrowserAttachService.clear_owned_profile(cdp_url) -> bool
RufusManager.logout(country, cdp_url, include_browser_profile) -> dict
opscli amazon-rufus logout COUNTRY
```

The CLI returns:

```json
{
  "success": true,
  "command": "amazon-rufus logout",
  "data": {
    "country": "US",
    "state_deleted": true,
    "browser_profile_deleted": true,
    "mcp_state_cleared": true
  },
  "error": null
}
```

## Safety

Profile deletion must resolve the target path and verify it stays under:

```text
~/.opscli/chrome-profiles
```

Only directories named `amazon-rufus-<PORT>` may be removed.

## References

Detailed research, PRD, architecture, and UX are in:

```text
output/ops-amazon-rufus-clear-login-research.md
output/ops-amazon-rufus-clear-login-prd.md
output/ops-amazon-rufus-clear-login-architecture.md
output/ops-amazon-rufus-clear-login-uiux.md
```
