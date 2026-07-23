import { describe, expect, it } from "vitest";
import { loginHref, safeReturnTo } from "@/auth/returnTo";

describe("safeReturnTo", () => {
  it("keeps only local application locations", () => {
    expect(safeReturnTo("/orders?status=open#row-2")).toBe("/orders?status=open#row-2");
    expect(safeReturnTo("https://example.test")).toBe("/");
    expect(safeReturnTo("//example.test")).toBe("/");
    expect(safeReturnTo("/\\example.test")).toBe("/");
  });

  it("encodes the validated return path for the OIDC start endpoint", () => {
    expect(loginHref("/orders?status=open")).toBe("/api/v1/auth/login?return_to=%2Forders%3Fstatus%3Dopen");
  });
});
