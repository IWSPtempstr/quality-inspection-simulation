import { afterEach, describe, expect, it } from "vitest";
import { demoSessionForRole, isDemoMode } from "@/mocks/demo";
import { useSessionStore } from "@/auth/sessionStore";

describe("demo acceptance mode", () => {
  afterEach(() => {
    useSessionStore.setState({ session: null });
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("starts only for an explicit development demo flag", () => {
    expect(isDemoMode({ DEV: true, VITE_DEMO_MODE: "true" })).toBe(true);
    expect(isDemoMode({ DEV: true, VITE_DEMO_MODE: "false" })).toBe(false);
    expect(isDemoMode({ DEV: false, VITE_DEMO_MODE: "true" })).toBe(false);
  });

  it.each(["admin", "scheduler", "operator", "viewer"] as const)("switches the in-memory session to %s", (role) => {
    useSessionStore.getState().setSession(demoSessionForRole(role));

    expect(useSessionStore.getState().session).toMatchObject({ role });
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);
  });
});
