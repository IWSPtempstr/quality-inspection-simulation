import type { Role, Session } from "@/api/types";

type DemoEnvironment = Pick<ImportMetaEnv, "DEV" | "VITE_DEMO_MODE">;

export function isDemoMode(environment: DemoEnvironment) {
  return environment.DEV && environment.VITE_DEMO_MODE === "true";
}

const demoSessions: Record<Role, Session> = {
  admin: { user_id: "demo-admin-001", role: "admin", display_name: "演示管理员" },
  scheduler: { user_id: "demo-scheduler-001", role: "scheduler", display_name: "演示调度员" },
  operator: { user_id: "demo-operator-001", role: "operator", display_name: "演示操作员" },
  viewer: { user_id: "demo-viewer-001", role: "viewer", display_name: "演示查看员" },
};

export function demoSessionForRole(role: Role): Session {
  return demoSessions[role];
}
