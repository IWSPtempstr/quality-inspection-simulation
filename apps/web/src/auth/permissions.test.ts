import { describe, expect, it } from "vitest";
import { can } from "@/auth/permissions";

describe("role permissions", () => {
  it("permits schedulers to approve schedules but not execute steps", () => {
    expect(can("scheduler", "schedule:write")).toBe(true);
    expect(can("scheduler", "execution:write")).toBe(false);
  });

  it("keeps viewers read-only", () => {
    expect(can("viewer", "schedule:read")).toBe(true);
    expect(can("viewer", "orders:write")).toBe(false);
  });

  it("keeps system health status admin-only", () => {
    expect(can("admin", "system:read")).toBe(true);
    expect(can("scheduler", "system:read")).toBe(false);
  });
});
