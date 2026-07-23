import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { showcaseFacts, showcaseOrders } from "@/showcase/data";

export const SHOWCASE_WORKBENCH_ROUTES = ["/", "/orders", "/resources", "/scheduling", "/execution", "/events", "/knowledge", "/notifications", "/admin/audit", "/admin/system"] as const;

const pages = [
  ["/", "总览", ["当前订单负载受控", "候选排程等待审核", "资源事件已进入处理队列"]],
  ["/orders", "订单", showcaseOrders.map((order) => `${order.id} · ${order.sample_name} · ${order.status}`)],
  ["/resources", "资源", showcaseFacts.resources],
  ["/scheduling", "排程", showcaseFacts.scheduling],
  ["/execution", "执行", showcaseFacts.execution],
  ["/events", "事件", showcaseFacts.events],
  ["/knowledge", "标准知识", showcaseFacts.knowledge],
  ["/notifications", "通知", showcaseFacts.notifications],
  ["/admin/audit", "审计", showcaseFacts.audit],
  ["/admin/system", "系统状态", showcaseFacts.health],
] as const;

export function PublicShowcaseApp() {
  const repositoryUrl = import.meta.env.VITE_SHOWCASE_REPOSITORY_URL || "https://github.com/";
  return <HashRouter><div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
    <header><strong>检测排程工作台</strong><p>公开产品展示</p><a href={repositoryUrl}>查看项目仓库</a><nav aria-label="展示导航">{pages.map(([path, title]) => <NavLink key={path} to={path} end={path === "/"} style={{ marginRight: 14 }}>{title}</NavLink>)}</nav></header>
    <Routes>{pages.map(([path, title, facts]) => <Route key={path} path={path} element={<ShowcasePage title={title} facts={facts} />} />)}</Routes>
  </div></HashRouter>;
}

function ShowcasePage({ title, facts }: { title: string; facts: readonly string[] }) {
  return <main><h1>{title}</h1><p>此页面以固定展示信息呈现，业务操作在公开展示中不可用。</p><ul>{facts.map((fact) => <li key={fact}>{fact}</li>)}</ul><button type="button" disabled aria-disabled="true">业务操作不可用</button></main>;
}
