import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, createIdempotencyKey } from "@/api/client";

afterEach(() => vi.unstubAllGlobals());

describe("apiRequest", () => {
  it("preserves a caller-supplied Idempotency-Key for a write", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/orders", { method: "POST", headers: { "Idempotency-Key": "order-create-001" } });

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("order-create-001");
  });

  it("creates a key callers can retain for a retry", () => {
    expect(createIdempotencyKey()).toEqual(expect.any(String));
  });
});
