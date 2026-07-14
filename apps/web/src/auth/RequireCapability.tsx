import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { can, type Capability } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { PermissionDenied } from "@/components/ui/PermissionDenied";

export function RequireCapability({ capability, children }: { capability: Capability; children: ReactNode }) {
  const session = useSessionStore((state) => state.session);
  const location = useLocation();
  if (!session) return <Navigate to="/" state={{ from: location }} replace />;
  return can(session.role, capability) ? <>{children}</> : <PermissionDenied />;
}
