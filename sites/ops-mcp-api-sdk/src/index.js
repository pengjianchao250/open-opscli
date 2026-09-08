const DEFAULT_TIMEOUT_MS = 15_000;

export class OpsMcpApiError extends Error {
  constructor(code, message, options = {}) {
    super(message);
    this.name = "OpsMcpApiError";
    this.code = code;
    if (options.status !== undefined) this.status = options.status;
  }
}

export function createOpsMcpApiClient(options = {}) {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError("timeoutMs must be a positive number");
  }

  function emit(type, details = {}) {
    if (typeof options.onEvent !== "function") return;
    try {
      options.onEvent({ type, ...details });
    } catch {
      // Diagnostic hooks must not interrupt requests.
    }
  }

  function getFetch() {
    const fetchImpl = options.fetchImpl ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") {
      throw sdkError("BROWSER_ENV_REQUIRED", "当前环境不支持 fetch");
    }
    return fetchImpl;
  }

  async function resolveAuth() {
    const operationToken = normalizeBearerToken(
      await callProvider(
        options.operationTokenProvider ?? defaultOperationTokenProvider,
        "OPS 登录信息",
      ),
    );
    const sessionId = normalizeValue(
      await callProvider(options.sessionIdProvider ?? defaultSessionIdProvider, "OPS Session"),
    );
    if (!operationToken && !sessionId) {
      throw sdkError("OPS_LOGIN_REQUIRED", "未找到 AppHub 登录信息，请先登录 OPS 系统");
    }

    const suppliedUser = await callProvider(
      options.currentUserProvider ?? (() => defaultCurrentUserProvider(operationToken)),
      "AppHub 用户信息",
    );
    const user = normalizeUser(suppliedUser);
    if (!sessionId && !user.email) {
      throw sdkError("OPS_LOGIN_REQUIRED", "AppHub viewer 身份缺少用户邮箱");
    }
    return { operationToken, sessionId, user };
  }

  function resolveBaseUrl() {
    const configured = options.apiBaseUrl ?? globalThis.location?.origin;
    const apiBaseUrl = normalizeBaseUrl(configured);
    if (!apiBaseUrl) {
      throw sdkError("BROWSER_ENV_REQUIRED", "未配置 MCP REST API 地址");
    }
    assertAllowedOrigin(apiBaseUrl, options.allowedApiOrigins);
    return apiBaseUrl;
  }

  async function request(path, init = {}) {
    const apiBaseUrl = resolveBaseUrl();
    const url = resolveApiUrl(path, apiBaseUrl);
    const auth = await resolveAuth();
    const headers = new Headers(init.headers);
    headers.delete("Authorization");
    headers.delete("X-MCP-API-Key");
    headers.delete("X-MCP-Proxy-Auth");
    if (auth.operationToken) headers.set("X-Ops-Token", auth.operationToken);
    if (auth.sessionId) headers.set("X-Session-Id", auth.sessionId);
    if (auth.user.email) headers.set("X-User-Email", auth.user.email);
    if (auth.user.id) headers.set("X-User-Id", auth.user.id);
    if (auth.user.name) headers.set("X-User-Name", auth.user.name);
    emit("auth_attached", {
      mode: auth.sessionId ? "session" : "viewer",
      targetOrigin: new URL(apiBaseUrl).origin,
    });

    let response;
    try {
      response = await fetchWithTimeout(
        getFetch(),
        url,
        {
          ...init,
          headers,
          credentials: "include",
          redirect: "error",
        },
        timeoutMs,
      );
    } catch (error) {
      if (error instanceof OpsMcpApiError) throw error;
      throw sdkError("REQUEST_FAILED", "MCP REST API 请求失败", { cause: error });
    }

    const authFailure = await classifyAuthFailure(response);
    if (authFailure === "authentication_required") {
      throw sdkError("OPS_LOGIN_REQUIRED", "AppHub 登录信息已失效，请重新登录", {
        status: 401,
      });
    }
    if (response.status === 403) {
      throw sdkError("PERMISSION_DENIED", "当前账号无权访问该接口", { status: 403 });
    }
    return response;
  }

  async function requestJson(path, init = {}) {
    const response = await request(path, init);
    try {
      return await response.json();
    } catch (error) {
      throw sdkError("RESPONSE_INVALID_JSON", "接口返回内容不是有效 JSON", {
        cause: error,
        status: response.status,
      });
    }
  }

  async function warmup() {
    resolveBaseUrl();
    await resolveAuth();
  }

  function invalidateCredentials() {
    emit("auth_invalidated");
  }

  return Object.freeze({ request, requestJson, warmup, invalidateCredentials });
}

let sharedClient = createOpsMcpApiClient();

export function configureOpsMcpApi(options = {}) {
  const previousClient = sharedClient;
  sharedClient = createOpsMcpApiClient(options);
  previousClient.invalidateCredentials();
  return opsMcpApi;
}

export const opsMcpApi = Object.freeze({
  request(path, init) {
    return sharedClient.request(path, init);
  },
  requestJson(path, init) {
    return sharedClient.requestJson(path, init);
  },
  warmup() {
    return sharedClient.warmup();
  },
  invalidateCredentials() {
    sharedClient.invalidateCredentials();
  },
});

function defaultOperationTokenProvider() {
  return readLocalStorage("OPERATION_TOKEN");
}

function defaultSessionIdProvider() {
  return readLocalStorage("OPERATION_USER_TOKEN") ?? readLocalStorage("OPS_SESSION_ID");
}

function defaultCurrentUserProvider(operationToken) {
  const stored = parseStoredUser();
  return stored ?? decodeJwtUser(operationToken) ?? {};
}

function readLocalStorage(key) {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function parseStoredUser() {
  for (const key of ["OPERATION_USER_INFO", "USER_INFO", "userInfo"]) {
    const raw = readLocalStorage(key);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // Ignore unrelated or legacy localStorage values.
    }
  }
  return null;
}

function decodeJwtUser(token) {
  const parts = String(token ?? "").split(".");
  if (parts.length !== 3) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const json = typeof globalThis.atob === "function"
      ? globalThis.atob(padded)
      : Buffer.from(padded, "base64").toString("utf8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function normalizeUser(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    email: normalizeValue(
      source.email ?? source.username ?? source.user_email ?? source.inherit_email,
    )?.toLowerCase() ?? null,
    id: normalizeValue(source.id ?? source.user_id ?? source.uuid),
    name: normalizeValue(source.name ?? source.display_name),
  };
}

function normalizeValue(value) {
  const normalized = String(value ?? "").trim();
  return normalized || null;
}

function normalizeBearerToken(value) {
  return String(value ?? "")
    .trim()
    .replace(/^authorization\s*:\s*/i, "")
    .replace(/^bearer\s+/i, "")
    .trim() || null;
}

async function callProvider(provider, label) {
  try {
    return await provider();
  } catch (error) {
    if (error instanceof OpsMcpApiError) throw error;
    throw sdkError("OPS_LOGIN_REQUIRED", `无法读取${label}`, { cause: error });
  }
}

function normalizeBaseUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (!new Set(["http:", "https:"]).has(url.protocol)) return null;
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function assertAllowedOrigin(apiBaseUrl, allowedApiOrigins) {
  if (!allowedApiOrigins) return;
  const allowed = new Set(allowedApiOrigins.map((value) => new URL(value).origin));
  if (!allowed.has(new URL(apiBaseUrl).origin)) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "MCP REST API 地址不在允许列表中");
  }
}

function resolveApiUrl(path, apiBaseUrl) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "仅允许以 / 开头的相对接口路径");
  }
  const url = new URL(path, `${apiBaseUrl}/`);
  if (url.origin !== new URL(apiBaseUrl).origin) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "接口路径不能指向其他来源");
  }
  if (url.searchParams.has("api_key")) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "REST 接口路径不得携带 MCP API Key");
  }
  return url.toString();
}

async function classifyAuthFailure(response) {
  if (response.status !== 401) return null;
  try {
    const payload = await response.clone().json();
    return payload?.error?.code ?? payload?.reason ?? payload?.code ?? null;
  } catch {
    return null;
  }
}

async function fetchWithTimeout(fetchImpl, input, init, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const externalSignal = init.signal;
  const abortFromExternalSignal = () => controller.abort(externalSignal.reason);
  if (externalSignal?.aborted) abortFromExternalSignal();
  else externalSignal?.addEventListener("abort", abortFromExternalSignal, { once: true });
  try {
    return await fetchImpl(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) throw sdkError("REQUEST_TIMEOUT", "请求超时", { cause: error });
    throw error;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abortFromExternalSignal);
  }
}

function sdkError(code, message, options) {
  return new OpsMcpApiError(code, message, options);
}
