/* eslint-disable react-refresh/only-export-components */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, useLocation } from "react-router-dom";
import { AppShell } from "@/app/AppShell";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { OrdersPage } from "@/features/orders/OrdersPage";
import { ResourcesPage } from "@/features/resources/ResourcesPage";
import { SchedulingPage } from "@/features/scheduling/SchedulingPage";
import { ExecutionPage } from "@/features/execution/ExecutionPage";
import { EventsPage } from "@/features/events/EventsPage";
import { KnowledgePage } from "@/features/knowledge/KnowledgePage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { AuditPage } from "@/features/admin/AuditPage";
import { SystemPage } from "@/features/admin/SystemPage";
import { apiRequest, clearCsrfToken, primeCsrfToken } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { Session } from "@/api/types";
import { RequireCapability } from "@/auth/RequireCapability";
import { useSessionStore } from "@/auth/sessionStore";
import { LoginPage } from "@/auth/LoginPage";

function currentReturnTo(pathname: string, search: string, hash: string): string {
  return `${pathname}${search}${hash}`;
}

export function SessionGate() {
  const setSession = useSessionStore((state) => state.setSession);
  const clearSession = useSessionStore((state) => state.clearSession);
  const location = useLocation();
  const usesDemoFixtures = import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === "true";
  const session = useQuery({ queryKey: queryKeys.session, queryFn: () => apiRequest<Session>("/session/me") });
  // MSW fixtures intentionally do not simulate a production browser session.
  const csrf = useQuery({ queryKey: ["auth", "csrf"], queryFn: primeCsrfToken, enabled: Boolean(session.data) && !usesDemoFixtures, retry: false });
  const sessionExpired = session.isError && session.error instanceof ApiProblem && session.error.problem.status === 401;
  useEffect(() => {
    if (!session.data) return;
    setSession(session.data);
  }, [session.data, setSession]);
  useEffect(() => {
    if (!sessionExpired) return;
    clearCsrfToken();
    clearSession();
  }, [clearSession, sessionExpired]);
  if (session.isLoading) return <main aria-busy="true">正在验证会话…</main>;
  if (sessionExpired) {
    const returnTo = currentReturnTo(location.pathname, location.search, location.hash);
    return <Navigate to={`/login?return_to=${encodeURIComponent(returnTo)}&reason=expired`} replace />;
  }
  if (session.isError) return <main role="status"><h1>服务暂不可用</h1><p>无法确认当前权限。请检查网络后重试。</p><button type="button" onClick={() => session.refetch()}>重试</button></main>;
  if (!usesDemoFixtures && csrf.isLoading) return <main aria-busy="true">正在建立安全会话…</main>;
  if (!usesDemoFixtures && csrf.isError) return <main role="status"><h1>服务暂不可用</h1><p>无法建立安全会话。请检查网络后重试。</p><button type="button" onClick={() => csrf.refetch()}>重试</button></main>;
  return <AppShell />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <SessionGate />,
    children: [
      { path: "/", element: <RequireCapability capability="schedule:read"><DashboardPage /></RequireCapability> },
      { path: "/dashboard", element: <Navigate to="/" replace /> },
      { path: "/orders", element: <RequireCapability capability="orders:read"><OrdersPage /></RequireCapability> },
      { path: "/resources", element: <RequireCapability capability="resources:read"><ResourcesPage /></RequireCapability> },
      { path: "/scheduling", element: <RequireCapability capability="schedule:read"><SchedulingPage /></RequireCapability> },
      { path: "/execution", element: <RequireCapability capability="execution:write"><ExecutionPage /></RequireCapability> },
      { path: "/events", element: <RequireCapability capability="events:read"><EventsPage /></RequireCapability> },
      { path: "/knowledge", element: <RequireCapability capability="knowledge:read"><KnowledgePage /></RequireCapability> },
      { path: "/notifications", element: <RequireCapability capability="notifications:read"><NotificationsPage /></RequireCapability> },
      { path: "/admin/audit", element: <RequireCapability capability="audit:read"><AuditPage /></RequireCapability> },
      { path: "/admin/system", element: <RequireCapability capability="system:read"><SystemPage /></RequireCapability> },
    ],
  },
]);
