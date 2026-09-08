import assert from "node:assert/strict";
import test from "node:test";

import {
  OpsMcpApiError,
  configureOpsMcpApi,
  createOpsMcpApiClient,
  opsMcpApi,
} from "../src/index.js";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createClient(fetchImpl, options = {}) {
  return createOpsMcpApiClient({
    apiBaseUrl: "https://ops.mcp.example.com",
    operationTokenProvider: () => "operation-token",
    currentUserProvider: () => ({
      email: "user@example.com",
      id: "u-1",
      name: "Demo User",
    }),
    fetchImpl,
    ...options,
  });
}

test("directly attaches AppHub viewer headers", async () => {
  const calls = [];
  const client = createClient(async (url, init) => {
    calls.push({ url: String(url), init });
    return jsonResponse({ success: true, data: ["ok"] });
  });

  const result = await client.requestJson("/api/v1/keepa/scenarios", {
    headers: {
      Authorization: "Bearer stale-mcp-key",
      "X-MCP-API-Key": "stale-mcp-key",
      "X-MCP-Proxy-Auth": "Bearer stale-mcp-key",
      "X-Test": "yes",
    },
  });

  assert.deepEqual(result, { success: true, data: ["ok"] });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://ops.mcp.example.com/api/v1/keepa/scenarios");
  assert.equal(calls[0].init.headers.get("X-Ops-Token"), "operation-token");
  assert.equal(calls[0].init.headers.get("X-User-Email"), "user@example.com");
  assert.equal(calls[0].init.headers.get("X-User-Id"), "u-1");
  assert.equal(calls[0].init.headers.get("X-User-Name"), "Demo User");
  assert.equal(calls[0].init.headers.get("Authorization"), null);
  assert.equal(calls[0].init.headers.get("X-MCP-API-Key"), null);
  assert.equal(calls[0].init.headers.get("X-MCP-Proxy-Auth"), null);
  assert.equal(calls[0].init.headers.get("X-Test"), "yes");
  assert.equal(calls[0].init.credentials, "include");
});

test("attaches explicit AppHub session without requiring a viewer email", async () => {
  let captured;
  const client = createClient(async (_url, init) => {
    captured = init;
    return jsonResponse({ success: true });
  }, {
    operationTokenProvider: () => null,
    sessionIdProvider: () => "session-1",
    currentUserProvider: () => null,
  });

  await client.request("/api/v1/seller-sprite/scenarios");

  assert.equal(captured.headers.get("X-Session-Id"), "session-1");
  assert.equal(captured.headers.get("X-Ops-Token"), null);
  assert.equal(captured.credentials, "include");
});

test("maps AppHub authentication failures without API key refresh", async () => {
  let calls = 0;
  const client = createClient(async () => {
    calls += 1;
    return jsonResponse({ error: { code: "authentication_required" } }, 401);
  });

  await assert.rejects(
    client.request("/api/v1/keepa/run"),
    (error) => error instanceof OpsMcpApiError && error.code === "OPS_LOGIN_REQUIRED",
  );
  assert.equal(calls, 1);
});

test("maps forbidden responses", async () => {
  const client = createClient(async () => jsonResponse({}, 403));
  await assert.rejects(
    client.request("/api/v1/keepa/run"),
    (error) => error instanceof OpsMcpApiError && error.code === "PERMISSION_DENIED",
  );
});

test("warmup validates auth locally and performs no request", async () => {
  let calls = 0;
  const client = createClient(async () => {
    calls += 1;
    return jsonResponse({ success: true });
  });
  await client.warmup();
  assert.equal(calls, 0);
});

test("requires either an AppHub token or session", async () => {
  const client = createClient(async () => jsonResponse({ success: true }), {
    operationTokenProvider: () => null,
    sessionIdProvider: () => null,
  });
  await assert.rejects(
    client.warmup(),
    (error) => error instanceof OpsMcpApiError && error.code === "OPS_LOGIN_REQUIRED",
  );
});

test("requires a verified user email for viewer mode", async () => {
  const client = createClient(async () => jsonResponse({ success: true }), {
    currentUserProvider: () => null,
  });
  await assert.rejects(
    client.warmup(),
    (error) => error instanceof OpsMcpApiError && error.code === "OPS_LOGIN_REQUIRED",
  );
});

test("default providers read localStorage token, session and user", async () => {
  const originalLocalStorage = globalThis.localStorage;
  const values = {
    OPERATION_TOKEN: "Bearer stored-token",
    OPERATION_USER_TOKEN: "stored-session",
    OPERATION_USER_INFO: JSON.stringify({ username: "stored@example.com" }),
  };
  globalThis.localStorage = { getItem: (key) => values[key] ?? null };
  let headers;
  try {
    const client = createOpsMcpApiClient({
      apiBaseUrl: "https://ops.mcp.example.com",
      fetchImpl: async (_url, init) => {
        headers = init.headers;
        return jsonResponse({ success: true });
      },
    });
    await client.request("/api/v1/keepa/scenarios");
  } finally {
    if (originalLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = originalLocalStorage;
  }
  assert.equal(headers.get("X-Ops-Token"), "stored-token");
  assert.equal(headers.get("X-Session-Id"), "stored-session");
  assert.equal(headers.get("X-User-Email"), "stored@example.com");
});

test("only allows relative business paths", async () => {
  const client = createClient(async () => jsonResponse({ success: true }));
  await assert.rejects(
    client.request("https://attacker.example.com/api"),
    (error) => error instanceof OpsMcpApiError && error.code === "TARGET_ORIGIN_NOT_ALLOWED",
  );
  await assert.rejects(
    client.request("/api/v1/keepa/run?api_key=stale-mcp-key"),
    (error) => error instanceof OpsMcpApiError && error.code === "TARGET_ORIGIN_NOT_ALLOWED",
  );
});

test("shared client keeps its stable object reference", async () => {
  const reference = opsMcpApi;
  let called = false;
  const configured = configureOpsMcpApi({
    apiBaseUrl: "http://127.0.0.1:9876",
    operationTokenProvider: () => "token",
    currentUserProvider: () => ({ email: "user@example.com" }),
    fetchImpl: async () => {
      called = true;
      return jsonResponse({ success: true });
    },
  });
  try {
    await opsMcpApi.request("/api/v1/keepa/scenarios");
  } finally {
    configureOpsMcpApi();
  }
  assert.equal(configured, reference);
  assert.equal(opsMcpApi, reference);
  assert.equal(called, true);
});
