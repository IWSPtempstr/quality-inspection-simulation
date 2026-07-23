import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, clearCsrfToken, createIdempotencyKey, primeCsrfToken } from "@/api/client";

afterEach(() => { clearCsrfToken(); vi.unstubAllGlobals(); });

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

  it("uses the BFF session for a G4-G7 Go request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/orders");

    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe("include");
  });

  it("uses the BFF session for a G8 Go facade request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ degraded: false }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/events/event-001/diagnose", { method: "POST", body: JSON.stringify({}) });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe("include");
  });

  it("does not override the request strategy for a knowledge fixture route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ answer: "fixture" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/knowledge/query", { method: "POST", body: JSON.stringify({ query: "CCC" }) });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBeUndefined();
  });

  it("keeps the CSRF token in memory and adds it to unsafe Go requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "session-bound-csrf" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const setItem = vi.spyOn(Storage.prototype, "setItem");

    await primeCsrfToken();
    await apiRequest("/orders", { method: "POST", body: JSON.stringify({}) });

    const [, request] = fetchMock.mock.calls[1];
    expect(new Headers(request.headers).get("X-CSRF-Token")).toBe("session-bound-csrf");
    expect(setItem).not.toHaveBeenCalled();
  });
});
