import { ApiProblem } from "@/api/problem";
import { isGoOwnedPath } from "@/api/ownership";
import { isPublicShowcase } from "@/showcase/mode";
import { showcaseRequest } from "@/showcase/request";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;

export type IdempotencyKey = string;

export function createIdempotencyKey(): IdempotencyKey {
  return crypto.randomUUID();
}

function isUnsafeMethod(method: string | undefined): boolean {
  return Boolean(method && !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase()));
}

/** Stores the session-bound CSRF token only for the lifetime of this page. */
export async function primeCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  if (!csrfRequest) {
    csrfRequest = fetch(`${apiBaseUrl}/auth/csrf`, { credentials: "include" })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new ApiProblem({ status: response.status, ...payload });
        if (typeof payload.csrf_token !== "string" || payload.csrf_token.length === 0) {
          throw new ApiProblem({ status: 503, title: "服务暂不可用", detail: "无法建立安全会话" });
        }
        const token = payload.csrf_token;
        csrfToken = token;
        return token;
      })
      .finally(() => { csrfRequest = null; });
  }
  return csrfRequest;
}

export function clearCsrfToken(): void {
  csrfToken = null;
  csrfRequest = null;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (isPublicShowcase()) return showcaseRequest<T>(path, init);
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && !["GET", "HEAD"].includes(init.method) && !headers.has("Idempotency-Key")) headers.set("Idempotency-Key", createIdempotencyKey());
  if (isGoOwnedPath(path) && isUnsafeMethod(init.method) && !headers.has("X-CSRF-Token") && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers, credentials: init.credentials ?? (isGoOwnedPath(path) ? "include" : undefined) });
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiProblem({ status: response.status, ...payload });
  return payload as T;
}
