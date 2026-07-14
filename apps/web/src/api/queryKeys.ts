export const queryKeys = {
  session: ["session"] as const,
  orders: (query = "") => ["orders", query] as const,
  resources: ["resources"] as const,
  schedule: ["schedule"] as const,
  previews: ["schedule-previews"] as const,
  events: ["events"] as const,
  notifications: ["notifications"] as const,
  audit: ["audit"] as const,
  health: ["health"] as const,
  assistance: (scope: string, id: string) => ["assistance", scope, id] as const,
};
