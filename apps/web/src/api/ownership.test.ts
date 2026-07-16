import { describe, expect, it } from "vitest";
import { isGoOwnedPath } from "@/api/ownership";

describe("frontend API ownership", () => {
  it.each([
    "/orders",
    "/resources/equipment",
    "/schedule-previews",
    "/schedule-steps/step-1/start",
    "/events/evt-1/close",
    "/notifications/not-1/read",
    "/system/health",
    "/schedule-previews/preview-1/explanation",
    "/schedule-previews/preflight",
    "/events/evt-1/diagnose",
    "/events/evt-1/case-candidates",
    "/exception-case-candidates/candidate-1/submit",
    "/notification-drafts",
    "/notification-drafts/draft-1/send",
    "/audit-logs/filter-suggestions",
  ])("routes %s to Go", (path) => {
    expect(isGoOwnedPath(path)).toBe(true);
  });

  it.each([
    "/knowledge/query",
    "/knowledge/impact-analysis",
    "/audit-logs",
  ])("keeps %s under fixture ownership until its Go contract is delivered", (path) => {
    expect(isGoOwnedPath(path)).toBe(false);
  });
});
