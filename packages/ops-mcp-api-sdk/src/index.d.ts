export interface OpsMcpApiEvent {
  type:
    | "credential_fetch_start"
    | "credential_fetch_success"
    | "credential_refresh"
    | "credential_invalidated";
  targetOrigin?: string;
  reason?: "invalid_api_key";
}

export interface OpsMcpApiClientOptions {
  apiBaseUrl?: string;
  configEndpoint?: string;
  operationTokenProvider?: () => string | null | Promise<string | null>;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  allowedConfigOrigins?: readonly string[];
  allowedApiOrigins?: readonly string[];
  onEvent?: (event: OpsMcpApiEvent) => void;
}

export interface OpsMcpApiClient {
  request(path: string, init?: RequestInit): Promise<Response>;
  requestJson<T = unknown>(path: string, init?: RequestInit): Promise<T>;
  warmup(): Promise<void>;
  invalidateCredentials(): void;
}

export class OpsMcpApiError extends Error {
  constructor(code: string, message: string, options?: { status?: number });
  readonly code: string;
  readonly status?: number;
}

export function createOpsMcpApiClient(
  options?: OpsMcpApiClientOptions,
): OpsMcpApiClient;

export function configureOpsMcpApi(
  options?: OpsMcpApiClientOptions,
): OpsMcpApiClient;

export const opsMcpApi: OpsMcpApiClient;
