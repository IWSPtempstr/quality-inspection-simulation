import type { Role } from "@/api/types";

export type Capability = "orders:read" | "orders:write" | "resources:read" | "schedule:read" | "schedule:write" | "execution:write" | "events:read" | "events:write" | "knowledge:read" | "notifications:read" | "audit:read" | "system:read";

const permissions: Record<Role, Array<Capability | "*">> = {
  admin: ["*"],
  scheduler: ["orders:read", "orders:write", "resources:read", "schedule:read", "schedule:write", "events:read", "events:write", "knowledge:read", "notifications:read", "audit:read"],
  operator: ["execution:write", "notifications:read"],
  viewer: ["orders:read", "resources:read", "schedule:read", "events:read", "knowledge:read", "notifications:read"],
};

export function can(role: Role | undefined, capability: Capability) { return Boolean(role && (permissions[role].includes("*") || permissions[role].includes(capability))); }
