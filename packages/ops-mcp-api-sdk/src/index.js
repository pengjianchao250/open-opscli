const DEFAULT_CONFIG_ENDPOINT = "/api/v1/mcp-api-keys/config";
const DEFAULT_TIMEOUT_MS = 15_000;
const PREFERRED_MCP_SERVER = "BI运营系统";

/** SDK 对外暴露的稳定错误类型。 */
export class OpsMcpApiError extends Error {
  constructor(code, message, options = {}) {
    // 原始异常可能包含请求地址，公开错误只保留稳定错误码和 HTTP 状态。
    super(message);
    this.name = "OpsMcpApiError";
    this.code = code;
    if (options.status !== undefined) this.status = options.status;
  }
}

/**
 * 创建 OPS MCP REST API 客户端。
 *
 * API Key 只缓存在当前实例内存中，不会返回给调用方或写入浏览器存储。
 */
export function createOpsMcpApiClient(options = {}) {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError("timeoutMs must be a positive number");
  }

  let cachedCredential = null;
  let credentialPromise = null;
  let credentialGeneration = 0;

  function emit(type, details = {}) {
    if (typeof options.onEvent !== "function") return;
    try {
      options.onEvent({ type, ...details });
    } catch {
      // 诊断回调不能中断认证或业务请求。
    }
  }

  function getFetch() {
    const fetchImpl = options.fetchImpl ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") {
      throw sdkError("BROWSER_ENV_REQUIRED", "当前环境不支持 fetch");
    }
    return fetchImpl;
  }

  async function getOperationToken() {
    const provider = options.operationTokenProvider ?? defaultOperationTokenProvider;
    let token;
    try {
      token = normalizeBearerToken(await provider());
    } catch (error) {
      if (error instanceof OpsMcpApiError) throw error;
      throw sdkError("OPS_LOGIN_REQUIRED", "无法读取 OPS 登录信息", { cause: error });
    }
    if (!token) {
      throw sdkError("OPS_LOGIN_REQUIRED", "未找到 OPS 登录信息，请先登录 OPS 系统");
    }
    return token;
  }

  async function exchangeCredential() {
    const operationToken = await getOperationToken();
    const configUrl = resolveConfigUrl(options.configEndpoint ?? DEFAULT_CONFIG_ENDPOINT);
    assertAllowedConfigOrigin(configUrl, options.allowedConfigOrigins);
    emit("credential_fetch_start");

    let response;
    try {
      response = await fetchWithTimeout(
        getFetch(),
        configUrl,
        {
          method: "GET",
          headers: {
            Accept: "application/json",
            Authorization: `Bearer ${operationToken}`,
          },
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
        },
        timeoutMs,
      );
    } catch (error) {
      if (error instanceof OpsMcpApiError) throw error;
      throw sdkError("CONFIG_FETCH_FAILED", "MCP API 配置获取失败", { cause: error });
    }

    if (response.status === 401 || response.status === 403) {
      throw sdkError("OPS_LOGIN_REQUIRED", "OPS 登录信息已失效，请重新登录", {
        status: response.status,
      });
    }
    if (!response.ok) {
      throw sdkError("CONFIG_FETCH_FAILED", "MCP API 配置获取失败", {
        status: response.status,
      });
    }

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw sdkError("CONFIG_INVALID", "MCP API 配置不是有效 JSON", { cause: error });
    }
    if (payload?.success !== true || !payload.data || typeof payload.data !== "object") {
      throw sdkError("CONFIG_INVALID", "MCP API 配置结构无效");
    }

    const credential = parseCredential(payload.data, options.apiBaseUrl);
    assertAllowedOrigin(credential.apiBaseUrl, options.allowedApiOrigins);
    emit("credential_fetch_success", { targetOrigin: new URL(credential.apiBaseUrl).origin });
    return credential;
  }

  async function getCredential() {
    if (isCredentialUsable(cachedCredential)) return cachedCredential;
    if (!credentialPromise) {
      // 所有并发调用复用同一个换取 Promise，避免配置接口被突发请求打满。
      const generation = credentialGeneration;
      const currentPromise = exchangeCredential()
        .then((credential) => {
          if (generation !== credentialGeneration) return getCredential();
          cachedCredential = credential;
          return credential;
        })
        .finally(() => {
          if (credentialPromise === currentPromise) credentialPromise = null;
        });
      credentialPromise = currentPromise;
    }
    return credentialPromise;
  }

  async function refreshCredential(staleCredential) {
    if (isCredentialUsable(cachedCredential) && cachedCredential !== staleCredential) {
      return cachedCredential;
    }
    if (cachedCredential === staleCredential) cachedCredential = null;
    return getCredential();
  }

  async function send(path, init, credential) {
    const url = resolveApiUrl(path, credential.apiBaseUrl);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${credential.apiKey}`);

    try {
      return await fetchWithTimeout(
        getFetch(),
        url,
        {
          ...init,
          headers,
          credentials: "omit",
          redirect: "error",
        },
        timeoutMs,
      );
    } catch (error) {
      if (error instanceof OpsMcpApiError) throw error;
      throw sdkError("REQUEST_FAILED", "MCP API 请求失败", { cause: error });
    }
  }

  async function classifyAuthFailure(response) {
    if (response.status === 403) return "permission_denied";
    if (response.status !== 401) return null;
    try {
      const payload = await response.clone().json();
      return payload?.reason ?? payload?.error?.code ?? payload?.code ?? null;
    } catch {
      return null;
    }
  }

  /** 发送自动携带 MCP API Key 的请求。 */
  async function request(path, init = {}) {
    const credential = await getCredential();
    let response = await send(path, init, credential);
    let authFailure = await classifyAuthFailure(response);

    if (authFailure === "invalid_api_key") {
      emit("credential_refresh", { reason: "invalid_api_key" });
      const refreshedCredential = await refreshCredential(credential);
      response = await send(path, init, refreshedCredential);
      authFailure = await classifyAuthFailure(response);
      if (authFailure === "invalid_api_key") {
        throw sdkError("API_KEY_REJECTED", "MCP API Key 已失效", { status: 401 });
      }
    }

    if (authFailure === "authentication_required") {
      throw sdkError("OPS_LOGIN_REQUIRED", "当前 MCP API Key 未绑定有效的 OPS 登录信息", {
        status: 401,
      });
    }
    if (authFailure === "permission_denied") {
      throw sdkError("PERMISSION_DENIED", "当前账号无权访问该接口", { status: 403 });
    }
    return response;
  }

  /** 发送请求并解析 JSON 响应。 */
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

  /** 提前完成凭证换取，避免首个业务请求承担初始化延迟。 */
  async function warmup() {
    await getCredential();
  }

  /** 清除当前实例的内存凭证，下次请求会重新换取。 */
  function invalidateCredentials() {
    credentialGeneration += 1;
    cachedCredential = null;
    credentialPromise = null;
    emit("credential_invalidated");
  }

  return Object.freeze({ request, requestJson, warmup, invalidateCredentials });
}

let sharedClient = createOpsMcpApiClient();

/**
 * 统一配置共享客户端，并保持 opsMcpApi 的对象引用不变。
 *
 * 应在应用入口调用；重新配置后，后续请求会使用新实例和新凭证缓存。
 */
export function configureOpsMcpApi(options = {}) {
  const previousClient = sharedClient;
  sharedClient = createOpsMcpApiClient(options);
  previousClient.invalidateCredentials();
  return opsMcpApi;
}

/** 可在所有业务模块中复用的共享客户端。 */
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
  if (!globalThis.localStorage) {
    throw sdkError("BROWSER_ENV_REQUIRED", "当前环境无法读取 localStorage.OPERATION_TOKEN");
  }
  return globalThis.localStorage.getItem("OPERATION_TOKEN");
}

function normalizeBearerToken(value) {
  return String(value ?? "")
    .trim()
    .replace(/^authorization\s*:\s*/i, "")
    .replace(/^bearer\s+/i, "")
    .trim();
}

function resolveConfigUrl(endpoint) {
  try {
    if (/^https?:\/\//i.test(endpoint)) return new URL(endpoint).toString();
    if (!globalThis.location?.origin) {
      throw sdkError("BROWSER_ENV_REQUIRED", "相对配置地址只能在浏览器环境中使用");
    }
    return new URL(endpoint, globalThis.location.origin).toString();
  } catch (error) {
    if (error instanceof OpsMcpApiError) throw error;
    throw sdkError("CONFIG_INVALID", "MCP API 配置地址无效", { cause: error });
  }
}

function parseCredential(data, configuredApiBaseUrl) {
  const structured = data.api;
  let apiKey = null;
  let discoveredBaseUrl = null;
  let expiresAt = null;

  if (structured && typeof structured === "object") {
    const structuredKey = normalizeBearerToken(structured.apiKey);
    const structuredBaseUrl = normalizeBaseUrl(structured.baseUrl);
    if (structuredKey && structuredBaseUrl) {
      if (structured.tokenType && String(structured.tokenType).toLowerCase() !== "bearer") {
        throw sdkError("CONFIG_INVALID", "MCP API 配置只支持 Bearer Token");
      }
      apiKey = structuredKey;
      discoveredBaseUrl = structuredBaseUrl;
      expiresAt = parseExpiresAt(structured.expiresAt);
    }
  }

  // 结构化配置未完整提供时，整组回退旧 MCP URL，避免混用不同来源的 Key 和地址。
  if (!apiKey) {
    const server = data.http?.mcpServers?.[PREFERRED_MCP_SERVER];
    if (!server || server.type !== "http" || typeof server.url !== "string") {
      throw sdkError("CONFIG_INVALID", "MCP API 配置缺少 BI运营系统 HTTP 地址");
    }
    let mcpUrl;
    try {
      mcpUrl = new URL(server.url);
    } catch (error) {
      throw sdkError("CONFIG_INVALID", "MCP HTTP 地址无效", { cause: error });
    }
    apiKey = normalizeBearerToken(mcpUrl.searchParams.get("api_key"));
    discoveredBaseUrl = mcpUrl.origin;
  }

  if (!apiKey) {
    throw sdkError("MCP_API_KEY_MISSING", "MCP API 配置缺少 API Key");
  }

  const apiBaseUrl = normalizeBaseUrl(configuredApiBaseUrl ?? discoveredBaseUrl);
  if (!apiBaseUrl) throw sdkError("CONFIG_INVALID", "MCP API 基础地址无效");

  return Object.freeze({ apiKey, apiBaseUrl, expiresAt });
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

function parseExpiresAt(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    return value < 10_000_000_000 ? value * 1000 : value;
  }
  const parsed = Date.parse(String(value));
  if (Number.isNaN(parsed)) {
    throw sdkError("CONFIG_INVALID", "MCP API 配置的 expiresAt 无效");
  }
  return parsed;
}

function isCredentialUsable(credential) {
  if (!credential) return false;
  return credential.expiresAt === null || credential.expiresAt - Date.now() > 30_000;
}

function assertAllowedOrigin(apiBaseUrl, allowedApiOrigins) {
  if (!allowedApiOrigins) return;
  const allowed = new Set(allowedApiOrigins.map((value) => requireOrigin(value)));
  if (!allowed.has(new URL(apiBaseUrl).origin)) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "MCP API 地址不在允许列表中");
  }
}

function assertAllowedConfigOrigin(configUrl, allowedConfigOrigins) {
  const configOrigin = new URL(configUrl).origin;
  const pageOrigin = normalizeOrigin(globalThis.location?.origin);
  const allowed = allowedConfigOrigins
    ? new Set(allowedConfigOrigins.map((value) => requireOrigin(value)))
    : pageOrigin
      ? new Set([pageOrigin])
      : null;

  if (allowed && !allowed.has(configOrigin)) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "MCP API 配置地址不在允许列表中");
  }
}

function normalizeOrigin(value) {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function requireOrigin(value) {
  const origin = normalizeOrigin(value);
  if (!origin) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "允许来源列表包含无效地址");
  }
  return origin;
}

function resolveApiUrl(path, apiBaseUrl) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "仅允许以 / 开头的相对接口路径");
  }
  const url = new URL(path, `${apiBaseUrl}/`);
  if (url.origin !== new URL(apiBaseUrl).origin) {
    throw sdkError("TARGET_ORIGIN_NOT_ALLOWED", "接口路径不能指向其他来源");
  }
  return url.toString();
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
    if (timedOut) {
      throw sdkError("REQUEST_TIMEOUT", "请求超时", { cause: error });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abortFromExternalSignal);
  }
}

function sdkError(code, message, options) {
  return new OpsMcpApiError(code, message, options);
}
