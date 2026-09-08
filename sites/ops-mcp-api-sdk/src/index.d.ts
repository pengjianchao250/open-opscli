export interface OpsMcpApiEvent {
  type:
    | "auth_attached"
    | "auth_invalidated";
  targetOrigin?: string;
  mode?: "viewer" | "session";
}

export interface OpsMcpApiCurrentUser {
  email?: string | null;
  username?: string | null;
  user_email?: string | null;
  inherit_email?: string | null;
  id?: string | number | null;
  user_id?: string | number | null;
  uuid?: string | null;
  name?: string | null;
  display_name?: string | null;
}

export interface OpsMcpApiClientOptions {
  apiBaseUrl?: string;
  operationTokenProvider?: () => string | null | Promise<string | null>;
  sessionIdProvider?: () => string | null | Promise<string | null>;
  currentUserProvider?: () =>
    | OpsMcpApiCurrentUser
    | null
    | Promise<OpsMcpApiCurrentUser | null>;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
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
