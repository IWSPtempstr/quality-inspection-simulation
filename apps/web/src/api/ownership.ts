const goOwnedPrefixes = [
  "/auth",
  "/session",
  "/orders",
  "/resources",
  "/schedules",
  "/schedule-previews",
  "/schedule-steps",
  "/events",
  "/notifications",
  "/system/health",
] as const;

const g8GoPrefixes = [
  "/exception-case-candidates",
  "/notification-drafts",
] as const;

const fixtureOnlyPrefixes = [
  "/knowledge",
] as const;

const g8GoNestedPaths = [
  /\/schedule-previews\/[^/]+\/explanation$/,
  /\/schedule-previews\/preflight$/,
  /\/events\/[^/]+\/(diagnose|case-candidates)$/,
  /\/audit-logs\/filter-suggestions$/,
] as const;

export function isGoOwnedPath(path: string): boolean {
  const pathname = path.split("?", 1)[0];
  if (fixtureOnlyPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) return false;
  if (g8GoPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) return true;
  if (g8GoNestedPaths.some((pattern) => pattern.test(pathname))) return true;
  return goOwnedPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
