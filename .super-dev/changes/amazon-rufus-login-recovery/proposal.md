# Proposal: amazon-rufus login recovery

## Summary

Improve the Rufus MCP failure recovery flow:

```text
amazon_rufus_get failure
  -> opscli amazon-rufus logout <COUNTRY> --pretty
  -> opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed
  -> retry amazon_rufus_get with original question source
```

`watch-login` must detect Amazon login completion from `#nav-tools` text or the `sso-state-main` / `at-main` Cookie names, then open the original ASIN product page and continue capturing `/rufus/cl/streaming`.

## Problem

The current `watch-login` implementation depends on `#nav-link-accountList-nav-line-1` / `#nav-link-accountList .nav-line-1`. Those elements are not consistently present on Amazon pages. When they are absent, the command can keep waiting even after the user has completed login and Amazon has returned to the homepage.

MCP failure recovery also needs to clear old Rufus state before opening a fresh login flow, otherwise old encrypted state or the opscli-owned Chrome profile can be reused.

## Goals

1. Detect login through `#nav-tools` i18n text or `sso-state-main` / `at-main` Cookie names.
2. Do not read or print Cookie values.
3. Open the original ASIN product page after login detection.
4. Update template Skill and installed `.agents` Skill docs with `logout -> watch-login -> retry`.
5. Keep MCP schema unchanged.

## Non-Goals

1. Do not add an MCP logout or recovery tool.
2. Do not add `watch-login --clear-before-login`.
3. Do not clear the user's default Chrome profile.
4. Do not change Rufus streaming request construction.

## References

```text
output/ops-amazon-rufus-clear-login-research.md
output/ops-amazon-rufus-clear-login-prd.md
output/ops-amazon-rufus-clear-login-architecture.md
output/ops-amazon-rufus-clear-login-uiux.md
```
