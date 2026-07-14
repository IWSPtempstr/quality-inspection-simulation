import { describe, expect, it } from "vitest";
import { orderSchema } from "@/features/orders/orderSchema";

describe("structured order validation", () => {
  it("requires employee-selected testing projects", () => {
    const result = orderSchema.safeParse({ sample_name: "空气炸锅", sample_quantity: 1, certification_type: "CCC", priority: "normal", promised_finish_time: "2026-07-16T17:00", project_ids: [] });
    expect(result.success).toBe(false);
  });
});
