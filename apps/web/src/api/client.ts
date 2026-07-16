import { ApiProblem } from "@/api/problem";
import { isGoOwnedPath } from "@/api/ownership";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export type IdempotencyKey = string;

export function createIdempotencyKey(): IdempotencyKey {
  return crypto.randomUUID();
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && !["GET", "HEAD"].includes(init.method) && !headers.has("Idempotency-Key")) headers.set("Idempotency-Key", createIdempotencyKey());
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: init.credentials ?? (isGoOwnedPath(path) ? "include" : undefined) });
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiProblem({ status: response.status, ...payload });
  return payload as T;
}
