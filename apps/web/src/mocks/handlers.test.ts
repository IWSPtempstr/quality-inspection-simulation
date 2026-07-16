import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { handlers } from "@/mocks/handlers";
import { server } from "@/mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("MSW public API fixtures", () => {
  it("keeps only G8 assistance routes in the default MSW handler set", () => {
    const handledPaths = handlers.map((handler) => handler.info.path);

    expect(handledPaths).toContain("*/api/v1/knowledge/query");
    expect(handledPaths).not.toContain("*/api/v1/orders");
    expect(handledPaths).not.toContain("*/api/v1/system/health");
  });

  it("returns the current scheduler session", async () => {
    const response = await fetch("http://localhost/api/v1/session/me");
    await expect(response.json()).resolves.toMatchObject({ role: "scheduler", user_id: "scheduler-001" });
  });

  it("returns the version-conflict problem response", async () => {
    const response = await fetch("http://localhost/api/v1/schedule-previews/PRE-20260714-004/approve", { method: "POST", headers: { "If-Match": "stale" } });
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toMatchObject({ title: "版本冲突", status: 409 });
  });

  it("returns an RFC 9457 conflict when an order patch uses the stale test version", async () => {
    const response = await fetch("http://localhost/api/v1/orders/ORD-20260714-001", { method: "PATCH", headers: { "Content-Type": "application/json", "If-Match": "stale" }, body: JSON.stringify({ priority: "urgent" }) });
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toMatchObject({ title: "版本冲突", status: 409, detail: "订单已被其他操作更新" });
  });

  it("creates an order retest with a valid reason", async () => {
    const response = await fetch("http://localhost/api/v1/orders/ORD-20260714-001/retests", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": "4" }, body: JSON.stringify({ reason: "结果异常" }) });
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toMatchObject({ id: "ORD-20260714-001-RETEST", status: "pending" });
  });

  it("rejects a retest requested against a stale order version", async () => {
    const response = await fetch("http://localhost/api/v1/orders/ORD-20260714-001/retests", { method: "POST", headers: { "Content-Type": "application/json", "If-Match": "stale" }, body: JSON.stringify({ reason: "结果异常" }) });
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toMatchObject({ title: "版本冲突", status: 409 });
  });

  it("returns a newly created order in later list reads", async () => {
    const create = await fetch("http://localhost/api/v1/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample_name: "新建样品", sample_quantity: 1, certification_type: "CCC", priority: "normal", promised_finish_time: "2026-07-16T09:00:00.000Z", project_ids: ["safety"] }) });
    expect(create.status).toBe(201);
    const list = await fetch("http://localhost/api/v1/orders?q=新建样品");
    await expect(list.json()).resolves.toMatchObject({ total: 1, items: [expect.objectContaining({ sample_name: "新建样品" })] });
  });

  it("replays an order creation for the same Idempotency-Key", async () => {
    const headers = { "Content-Type": "application/json", "Idempotency-Key": "order-create-replay-001" };
    const body = JSON.stringify({ sample_name: "幂等样品", sample_quantity: 1, certification_type: "CCC", priority: "normal", promised_finish_time: "2026-07-16T09:00:00.000Z", project_ids: ["safety"] });

    const first = await fetch("http://localhost/api/v1/orders", { method: "POST", headers, body });
    const second = await fetch("http://localhost/api/v1/orders", { method: "POST", headers, body });

    await expect(second.json()).resolves.toEqual(await first.json());
  });
});
