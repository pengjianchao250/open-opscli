# 卖家精灵远端MCP配置契约

## Purpose

This document freezes the backend config contract used by the public `opscli seller-sprite` CLI to discover the remote MCP endpoint.

This is a contract gate, not an implementation guide.

## Endpoint

`GET /api/v1/mcp-api-keys/config`

## Request Auth

The public CLI sends the existing auth material returned by `AuthClient.build_request_auth("ops")`. The request is not headers-only.

- `Authorization: Bearer <ops_jwt>`
- `X-Opscli-Version: <version>`
- Cookie: `polarisUserToken=<session_id>`
- Cookie: `opscliDeviceCode=<device_code>` when present in the existing auth flow output

The caller must already have a valid OPS login handled by the existing CLI auth flow. This endpoint only returns the remote MCP transport configuration for that authenticated identity.

## Success Response

```json
{
  "success": true,
  "data": {
    "http": {
      "mcpServers": {
        "BI运营系统": {
          "type": "http",
          "url": "https://<ops-mcp-host>/mcp?api_key=<issued_key>"
        }
      }
    }
  }
}
```

## Field Semantics

- `data.http.mcpServers`: remote MCP server registry for streamable HTTP transport
- `data.http.mcpServers.<name>.type`: transport type; the current gate freezes `"type": "http"`
- `data.http.mcpServers.<name>.url`: OPS general MCP URL, including the backend-issued user `api_key` query parameter

## Gate Rules

- public `opscli seller-sprite` only consumes `GET /api/v1/mcp-api-keys/config` for remote MCP discovery
- CLI auth is handled elsewhere; this contract does not introduce any dedicated auth-bridge endpoint
- public `opscli seller-sprite` CLI path is frozen to `data.http.mcpServers`
- the CLI must select `data.http.mcpServers.BI运营系统`; this is the OPS general MCP, not Collector MCP
- SellerSprite calls are forwarded from the OPS general MCP to Collector MCP; the CLI neither discovers nor configures the Collector address
- the public path only accepts HTTP transport entries from `data.http.mcpServers`
- URL logs and error messages must redact the `api_key` query value before output

## Notes

- This document replaces the obsolete assumption of a dedicated "JWT exchange to MCP key/base URL" endpoint.
- Alternate transport registries are out of scope for the frozen public-path contract in this document.
