import { Bell, BookOpen, CalendarClock, ClipboardList, Database, Gauge, LayoutDashboard, ListTodo, ServerCog, ShieldCheck, UsersRound } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import styles from "@/app/AppShell.module.css";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { demoSessionForRole } from "@/mocks/demo";
import type { Role } from "@/api/types";
import { isPublicShowcase } from "@/showcase/mode";

const navigation = [
  ["/", "总览", LayoutDashboard, "schedule:read"],
  ["/orders", "订单", ClipboardList, "orders:read"],
  ["/resources", "资源", UsersRound, "resources:read"],
  ["/scheduling", "排程", CalendarClock, "schedule:read"],
  ["/execution", "执行", ListTodo, "execution:write"],
  ["/events", "事件", Gauge, "events:read"],
  ["/knowledge", "标准知识", BookOpen, "knowledge:read"],
  ["/notifications", "通知", Bell, "notifications:read"],
] as const;

const administration = [
  ["/admin/audit", "审计", ShieldCheck, "audit:read"],
  ["/admin/system", "系统状态", ServerCog, "system:read"],
] as const;

export function AppShell() {
  const location = useLocation();
  const session = useSessionStore((state) => state.session);
  const setSession = useSessionStore((state) => state.setSession);
  const showcase = isPublicShowcase();
  const visibleNavigation = showcase ? navigation : navigation.filter(([, , , capability]) => can(session?.role, capability));
  const visibleAdministration = showcase ? administration : administration.filter(([, , , capability]) => can(session?.role, capability));
  const pageTitle = [...navigation, ...administration].find(([path]) => path === location.pathname)?.[1] ?? "工作台";

  return (
    <div className={styles.shell}>
      <a className="skipLink" href="#main-content">跳到主要内容</a>
      <aside className={styles.rail} aria-label="主导航">
        <div className={styles.brand}><Database aria-hidden="true" /><span>检测排程</span></div>
        <nav className={styles.navigation}>
          {visibleNavigation.map(([path, label, Icon]) => <NavItem key={path} path={path} label={label} Icon={Icon} />)}
          {visibleAdministration.length > 0 && <p className={styles.groupLabel}>管理</p>}
          {visibleAdministration.map(([path, label, Icon]) => <NavItem key={path} path={path} label={label} Icon={Icon} />)}
        </nav>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <div><p className={styles.crumb}>检测中心 / 工作台</p><strong>{pageTitle}</strong></div>
          <div className={styles.user} aria-label="当前用户">
            <span className={styles.presence} aria-hidden="true" />
            <span>{showcase ? "公开产品展示" : session?.display_name ?? "未知用户"}</span>
            <span>{showcase ? "只读" : session?.role ?? "未知角色"}</span>
            {import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === "true" && (
              <label className={styles.demoRole}>
                <span>演示角色</span>
                <select aria-label="演示角色" value={session?.role ?? "scheduler"} onChange={(event) => setSession(demoSessionForRole(event.target.value as Role))}>
                  <option value="admin">admin</option>
                  <option value="scheduler">scheduler</option>
                  <option value="operator">operator</option>
                  <option value="viewer">viewer</option>
                </select>
              </label>
            )}
          </div>
        </header>
        <main id="main-content" className={styles.content} tabIndex={-1}>{showcase ? <fieldset className={styles.showcaseReadOnly} disabled><Outlet /></fieldset> : <Outlet />}</main>
      </div>
    </div>
  );
}

function NavItem({ path, label, Icon }: { path: string; label: string; Icon: typeof LayoutDashboard }) {
  return <NavLink end={path === "/"} to={path} className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}><Icon aria-hidden="true" size={18} /><span>{label}</span></NavLink>;
}
