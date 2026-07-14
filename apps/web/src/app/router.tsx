/* eslint-disable react-refresh/only-export-components */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, Navigate } from "react-router-dom";
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
import { apiRequest } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Session } from "@/api/types";
import { RequireCapability } from "@/auth/RequireCapability";
import { useSessionStore } from "@/auth/sessionStore";

function SessionGate() {
  const setSession = useSessionStore((state) => state.setSession);
  const session = useQuery({ queryKey: queryKeys.session, queryFn: () => apiRequest<Session>("/session/me") });
  useEffect(() => { if (session.data) setSession(session.data); }, [session.data, setSession]);
  if (session.isLoading) return <main aria-busy="true">正在验证会话…</main>;
  if (session.isError) return <main><h1>服务暂不可用</h1><p>无法确认当前权限。请检查网络后重试。</p><button type="button" onClick={() => session.refetch()}>重试</button></main>;
  return <AppShell />;
}

export const router = createBrowserRouter([
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
