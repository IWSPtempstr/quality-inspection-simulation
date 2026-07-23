import { afterEach, describe, expect, it, vi } from "vitest";
import { isPublicShowcase } from "@/showcase/mode";

describe("public showcase mode", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is enabled only by the explicit public-showcase build flag", () => {
    vi.stubEnv("VITE_PUBLIC_SHOWCASE", "true");
    expect(isPublicShowcase()).toBe(true);

    vi.stubEnv("VITE_PUBLIC_SHOWCASE", "false");
    expect(isPublicShowcase()).toBe(false);
  });

  it("does not treat the development demo flag as a public showcase", () => {
    vi.stubEnv("VITE_PUBLIC_SHOWCASE", "");
    vi.stubEnv("VITE_DEMO_MODE", "true");

    expect(isPublicShowcase()).toBe(false);
  });
});
