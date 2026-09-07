import assert from "node:assert/strict";
import test from "node:test";

import {
  OpsMcpApiError,
  configureOpsMcpApi,
  createOpsMcpApiClient,
  opsMcpApi,
} from "../src/index.js";

const CONFIG_URL = "https://ops.example.com/api/v1/mcp-api-keys/config";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function configPayload(apiKey = "mcp_usr_demo", mcpOrigin = "https://ops.mcp.xenkee.com") {
  return {
    success: true,
    data: {
      http: {
        mcpServers: {
          "BI运营系统": {
            type: "http",
            url: mcpOrigin + "/mcp?api_key=" + apiKey,
          },
        },
      },
    },
  };
}

function createClient(fetchImpl, options = {}) {
  return createOpsMcpApiClient({
    configEndpoint: CONFIG_URL,
    operationTokenProvider: () => "operation-token",
    fetchImpl,
    ...options,
  });
}

test("换取 API Key 并自动注入业务请求 Authorization", async () => {
  const calls = [];
  const client = createClient(async (url, init) => {
    calls.push({ url: String(url), init });
    if (calls.length === 1) return jsonResponse(configPayload());
    return jsonResponse({ success: true, data: ["ok"] });
  });

  const result = await client.requestJson("/api/v1/keepa/scenarios", {
    headers: { Authorization: "Bearer caller-value", "X-Test": "yes" },
  });

  assert.deepEqual(result, { success: true, data: ["ok"] });
  assert.equal(calls[0].init.headers.Authorization, "Bearer operation-token");
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[1].url, "https://ops.mcp.xenkee.com/api/v1/keepa/scenarios");
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer mcp_usr_demo");
  assert.equal(calls[1].init.headers.get("X-Test"), "yes");
  assert.equal(calls[1].init.credentials, "omit");
});

test("并发请求共享一次凭证换取", async () => {
  let configCalls = 0;
  const client = createClient(async (url) => {
    if (String(url) === CONFIG_URL) {
      configCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return jsonResponse(configPayload());
    }
    return jsonResponse({ success: true });
  });

  await Promise.all([
    client.request("/api/v1/keepa/scenarios"),
    client.request("/api/v1/seller-sprite/scenarios"),
  ]);

  assert.equal(configCalls, 1);
});

test("仅在 invalid_api_key 时刷新并重试一次", async () => {
  let configCalls = 0;
  const businessKeys = [];
  const client = createClient(async (url, init) => {
    if (String(url) === CONFIG_URL) {
      configCalls += 1;
      return jsonResponse(configPayload("mcp_usr_" + configCalls));
    }
    businessKeys.push(init.headers.get("Authorization"));
    if (businessKeys.length === 1) {
      return jsonResponse({ reason: "invalid_api_key" }, 401);
    }
    return jsonResponse({ success: true });
  });

  const response = await client.request("/api/v1/keepa/scenarios");

  assert.equal(response.status, 200);
  assert.equal(configCalls, 2);
  assert.deepEqual(businessKeys, ["Bearer mcp_usr_1", "Bearer mcp_usr_2"]);
});

test("authentication_required 不刷新 API Key", async () => {
  let configCalls = 0;
  const client = createClient(async (url) => {
    if (String(url) === CONFIG_URL) {
      configCalls += 1;
      return jsonResponse(configPayload());
    }
    return jsonResponse({ error: { code: "authentication_required" } }, 401);
  });

  await assert.rejects(
    client.request("/api/v1/keepa/run"),
    (error) => error instanceof OpsMcpApiError && error.code === "OPS_LOGIN_REQUIRED",
  );
  assert.equal(configCalls, 1);
});

test("并发失效请求不会重复刷新新凭证", async () => {
  let configCalls = 0;
  let firstKeyCallCount = 0;
  let releaseFirstKeyCalls;
  const firstKeyCallsReady = new Promise((resolve) => {
    releaseFirstKeyCalls = resolve;
  });
  const client = createClient(async (url, init) => {
    if (String(url) === CONFIG_URL) {
      configCalls += 1;
      return jsonResponse(configPayload("mcp_usr_" + configCalls));
    }
    if (init.headers.get("Authorization") === "Bearer mcp_usr_1") {
      firstKeyCallCount += 1;
      if (firstKeyCallCount === 2) releaseFirstKeyCalls();
      await firstKeyCallsReady;
      return jsonResponse({ reason: "invalid_api_key" }, 401);
    }
    return jsonResponse({ success: true });
  });

  await Promise.all([
    client.request("/api/v1/keepa/scenarios"),
    client.request("/api/v1/seller-sprite/scenarios"),
  ]);

  assert.equal(configCalls, 2);
});

test("apiBaseUrl 覆盖配置接口返回的 API 地址", async () => {
  const calls = [];
  const client = createClient(async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url) === CONFIG_URL) return jsonResponse(configPayload());
    return jsonResponse({ success: true });
  }, { apiBaseUrl: "http://127.0.0.1:8765" });

  await client.request("/api/v1/keepa/scenarios");

  assert.equal(calls[1].url, "http://127.0.0.1:8765/api/v1/keepa/scenarios");
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer mcp_usr_demo");
});

test("共享实例可在应用入口统一切换 API 地址且引用保持不变", async () => {
  const sharedReference = opsMcpApi;
  const calls = [];
  const configuredClient = configureOpsMcpApi({
    apiBaseUrl: "http://127.0.0.1:9876",
    configEndpoint: CONFIG_URL,
    operationTokenProvider: () => "operation-token",
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (String(url) === CONFIG_URL) return jsonResponse(configPayload());
      return jsonResponse({ success: true });
    },
  });

  try {
    await opsMcpApi.request("/api/v1/keepa/scenarios");
  } finally {
    configureOpsMcpApi();
  }

  assert.equal(configuredClient, sharedReference);
  assert.equal(opsMcpApi, sharedReference);
  assert.equal(calls[1].url, "http://127.0.0.1:9876/api/v1/keepa/scenarios");
});

test("优先使用结构化 data.api 配置", async () => {
  const calls = [];
  const legacyPayload = configPayload("legacy-key", "https://legacy.example.com");
  const client = createClient(async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url) === CONFIG_URL) {
      return jsonResponse({
        ...legacyPayload,
        data: {
          ...legacyPayload.data,
          api: {
            baseUrl: "https://structured.example.com",
            apiKey: "structured-key",
            tokenType: "Bearer",
            expiresAt: null,
          },
        },
      });
    }
    return jsonResponse({ success: true });
  });

  await client.request("/api/v1/keepa/scenarios");

  assert.equal(calls[1].url, "https://structured.example.com/api/v1/keepa/scenarios");
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer structured-key");
});

test("不完整的 data.api 整组回退旧 MCP URL", async () => {
  const calls = [];
  const payload = configPayload("legacy-key", "https://legacy.example.com");
  payload.data.api = { baseUrl: "https://partial.example.com" };
  const client = createClient(async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url) === CONFIG_URL) return jsonResponse(payload);
    return jsonResponse({ success: true });
  });

  await client.request("/api/v1/keepa/scenarios");

  assert.equal(calls[1].url, "https://legacy.example.com/api/v1/keepa/scenarios");
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer legacy-key");
});

test("结构化配置拒绝无效 expiresAt", async () => {
  const payload = configPayload();
  payload.data.api = {
    baseUrl: "https://structured.example.com",
    apiKey: "structured-key",
    expiresAt: "not-a-date",
  };
  const client = createClient(async () => jsonResponse(payload));

  await assert.rejects(
    client.warmup(),
    (error) => error instanceof OpsMcpApiError && error.code === "CONFIG_INVALID",
  );
});

test("拒绝配置到白名单外的 API 来源", async () => {
  const client = createClient(
    async () => jsonResponse(configPayload()),
    { allowedApiOrigins: ["https://allowed.example.com"] },
  );

  await assert.rejects(
    client.warmup(),
    (error) =>
      error instanceof OpsMcpApiError && error.code === "TARGET_ORIGIN_NOT_ALLOWED",
  );
});

test("浏览器默认拒绝跨来源配置换取地址", async () => {
  const originalLocation = globalThis.location;
  globalThis.location = { origin: "https://ops.example.com" };
  try {
    const client = createClient(
      async () => jsonResponse(configPayload()),
      { configEndpoint: "https://attacker.example.com/config" },
    );
    await assert.rejects(
      client.warmup(),
      (error) =>
        error instanceof OpsMcpApiError && error.code === "TARGET_ORIGIN_NOT_ALLOWED",
    );
  } finally {
    if (originalLocation === undefined) delete globalThis.location;
    else globalThis.location = originalLocation;
  }
});

test("默认 Token Provider 延迟读取 localStorage.OPERATION_TOKEN", async () => {
  const originalLocalStorage = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: (key) => (key === "OPERATION_TOKEN" ? "Bearer stored-token" : null),
  };
  let configAuthorization;

  try {
    const client = createOpsMcpApiClient({
      configEndpoint: CONFIG_URL,
      fetchImpl: async (url, init) => {
        if (String(url) === CONFIG_URL) {
          configAuthorization = init.headers.Authorization;
          return jsonResponse(configPayload());
        }
        return jsonResponse({ success: true });
      },
    });
    await client.warmup();
  } finally {
    if (originalLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = originalLocalStorage;
  }

  assert.equal(configAuthorization, "Bearer stored-token");
});

test("相对配置地址在非浏览器环境返回稳定错误", async () => {
  const originalLocation = globalThis.location;
  delete globalThis.location;
  try {
    const client = createOpsMcpApiClient({
      operationTokenProvider: () => "operation-token",
      fetchImpl: async () => jsonResponse(configPayload()),
    });
    await assert.rejects(
      client.warmup(),
      (error) => error instanceof OpsMcpApiError && error.code === "BROWSER_ENV_REQUIRED",
    );
  } finally {
    if (originalLocation !== undefined) globalThis.location = originalLocation;
  }
});

test("仅允许相对业务路径", async () => {
  const client = createClient(async (url) => {
    if (String(url) === CONFIG_URL) return jsonResponse(configPayload());
    return jsonResponse({ success: true });
  });

  await assert.rejects(
    client.request("https://attacker.example.com/api"),
    (error) =>
      error instanceof OpsMcpApiError && error.code === "TARGET_ORIGIN_NOT_ALLOWED",
  );
});

test("invalidateCredentials 可使进行中的换取结果失效", async () => {
  let configCalls = 0;
  let releaseFirstConfig;
  const firstConfigReady = new Promise((resolve) => {
    releaseFirstConfig = resolve;
  });
  const client = createClient(async (url) => {
    if (String(url) !== CONFIG_URL) return jsonResponse({ success: true });
    configCalls += 1;
    if (configCalls === 1) await firstConfigReady;
    return jsonResponse(configPayload("mcp_usr_" + configCalls));
  });

  const warmup = client.warmup();
  await Promise.resolve();
  client.invalidateCredentials();
  releaseFirstConfig();
  await warmup;

  assert.equal(configCalls, 2);
});
