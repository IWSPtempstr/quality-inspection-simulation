import { expect, test, type Page, type Route } from "@playwright/test";
import { AxeBuilder } from "@axe-core/playwright";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

type Role = "admin" | "scheduler" | "operator" | "viewer";
type Json = Record<string, unknown>;

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const screenshotsDirectory = resolve(testsDirectory, "../../../docs/product/screenshots");
const apiPrefix = "/api/v1";
const at = "2026-07-14T09:00:00+08:00";

const pageResult = <T>(items: T[]) => ({ items, page: 1, page_size: 25, total: items.length });

function problem(route: Route, detail: string) {
  return route.fulfill({
    status: 409,
    contentType: "application/problem+json",
    body: JSON.stringify({ type: "about:blank", title: "版本冲突", status: 409, detail }),
  });
}

class BrowserApi {
  role: Role;
  approveConflicts = true;
  orders: Json[] = [
    { id: "ORD-20260714-001", sample_name: "空气炸锅 A8", sample_quantity: 3, certification_type: "CCC", priority: "vip", promised_finish_time: "2026-07-16T17:00:00+08:00", project_ids: ["safety", "emc"], status: "scheduled", version: 4, created_at: at },
  ];
  steps: Json[] = [
    { id: "STEP-001", order_id: "ORD-20260714-001", project_id: "safety", equipment_id: "SAFE-02", employee_ids: ["EMP-01"], starts_at: "2026-07-14T09:00:00+08:00", ends_at: "2026-07-14T11:00:00+08:00", status: "running", frozen: true, version: 3 },
    { id: "STEP-002", order_id: "ORD-20260714-001", project_id: "emc", equipment_id: "EMC-03", employee_ids: ["EMP-01"], starts_at: "2026-07-14T13:00:00+08:00", ends_at: "2026-07-14T16:00:00+08:00", status: "scheduled", frozen: false, version: 3 },
  ];
  preview: Json = {
    id: "PRE-20260714-004", status: "pending_review", algorithm_used: "cp_sat", solver_status: "feasible", fallback_used: false, fallback_reason: null, blockers: [],
    base_schedule_version: 12, resource_snapshot_version: 38, frozen_step_count: 1, changed_step_count: 2, delayed_order_count: 1,
    weighted_delay_minutes: 240, total_delay_minutes: 90, changes: [{ type: "moved", step_id: "STEP-002", from: "2026-07-14T11:30:00+08:00", to: "2026-07-14T13:00:00+08:00" }],
    schedule: { version: 13, steps: this.steps }, version: 1,
  };
  events: Json[] = [
    { id: "EVT-001", event_type: "equipment_failed", status: "open", severity: "high", entity_id: "ENV-01", version: 2, occurred_at: at, payload: { reason: "温控异常" } },
  ];
  notifications: Json[] = [
    { id: "NOT-01", title: "环境箱 01 故障影响待处理订单", status: "unread", created_at: at },
  ];
  audit: Json[] = [
    { id: "AUD-01", actor_id: "scheduler-001", action: "schedule_preview_created", created_at: at, detail: { preview_id: "PRE-20260714-004" } },
  ];

  constructor(role: Role) {
    this.role = role;
  }

  async install(page: Page) {
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private async handle(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.slice(url.pathname.indexOf(apiPrefix) + apiPrefix.length);
    const method = request.method();

    if (method === "GET" && path === "/session/me") return this.json(route, { user_id: `${this.role}-001`, role: this.role, display_name: this.role });
    if (method === "GET" && path === "/auth/csrf") return this.json(route, { csrf_token: `browser-session-${this.role}-csrf` });
    if (method === "GET" && path === "/system/health") return this.json(route, { status: "healthy", services: { api: "healthy", scheduler: "healthy" } });
    if (method === "GET" && path === "/orders") return this.json(route, pageResult(this.orders));
    if (method === "POST" && path === "/orders") {
      const input = request.postDataJSON() as Json;
      const order = { id: "ORD-20260714-099", status: "pending", version: 1, created_at: at, ...input };
      this.orders.unshift(order);
      return this.json(route, order, 201);
    }
    if (method === "GET" && path === "/schedules/current") return this.json(route, { version: 13, steps: this.steps });
    if (method === "GET" && path === "/schedule-previews") return this.json(route, pageResult([this.preview]));
    if (method === "POST" && path.endsWith("/explanation")) return this.json(route, { preview_id: "PRE-20260714-004", subject_type: "preview", subject_id: "PRE-20260714-004", summary: "候选保持运行中的安全步骤冻结，并将受环境箱维护影响的后续步骤延后。", constraint_reasons: ["STEP-001 正在运行，必须冻结"], tradeoffs: ["优先降低 VIP 订单延期"], frozen_step_ids: ["STEP-001"], blockers: [], fallback_reason: null, evidence_available: true, degraded: false });
    if (method === "POST" && path === "/schedule-previews/preflight") return this.json(route, { scope: "schedule_preview", status: "blocked", findings: [{ code: "equipment_unavailable", severity: "error", message: "环境箱 ENV-01 在维护窗口内不可用。", blocking: true, suggestion: "维护结束后重新选择可用设备或调整执行时间。" }], deterministic: true, explanation_available: true, degraded: false });
    if (method === "POST" && path.endsWith("/approve")) {
      if (this.approveConflicts) {
        this.approveConflicts = false;
        this.preview = { ...this.preview, version: 2 };
        return problem(route, "候选排程已被其他调度员处理");
      }
      this.preview = { ...this.preview, status: "approved", version: 3 };
      return this.json(route, this.preview);
    }
    if (method === "PATCH" && path.startsWith("/schedule-steps/")) {
      const id = path.split("/")[2];
      const action = path.split("/")[3];
      const index = this.steps.findIndex((step) => step.id === id);
      const current = this.steps[index];
      const updated = { ...current, status: action === "start" ? "running" : "completed", frozen: action === "start", version: Number(current.version) + 1 };
      this.steps[index] = updated;
      return this.json(route, updated);
    }
    if (method === "GET" && path === "/events") return this.json(route, pageResult(this.events));
    if (method === "GET" && path.startsWith("/events/")) return this.json(route, this.events.find((event) => event.id === path.split("/")[2]));
    if (method === "POST" && path.endsWith("/diagnose")) {
      return this.json(route, {
        event_id: "EVT-001", affected_order_ids: ["ORD-20260714-001"], sla_risks: [{ order_id: "ORD-20260714-001", risk: "承诺时间风险" }],
        frozen_step_ids: ["STEP-001"], affected_resources: [{ resource_id: "ENV-01", impact: "维护窗口内不可用于环境试验" }], evidence: [{ standard_title: "CCC 环境试验规范", version: "2026.1", clause: "6.3", page: 18, content: "设备异常时应停止相关项目并评估已排任务。" }],
        resolved_case_ids: ["CASE-01"], recommendations: ["保持运行中步骤冻结"], evidence_gaps: [], confidence: "high", tool_calls: ["get_event_snapshot", "get_schedule_snapshot", "search_standards"], degraded: false, memory_summary_status: "available",
      });
    }
    if (method === "POST" && path.endsWith("/case-candidates")) return this.json(route, { candidate_id: "candidate-signed-evt-001", event_id: "EVT-001", source_candidate_hash: "evt-001-v2", summary: "ENV-01 温控异常导致环境试验步骤阻塞。", trigger: "设备温控异常", impact: "ORD-20260714-001 存在 SLA 风险。", disposition: "冻结运行中步骤。", outcome: "待人工闭环确认", tags: ["equipment_failed"], evidence: [], retention_until: "2027-07-14T00:00:00+08:00", status: "candidate" });
    if (method === "POST" && path.startsWith("/exception-case-candidates/")) return this.json(route, { id: "CASE-REVIEW-001", event_id: "EVT-001", status: "pending_review", version: 1, submitted_at: at }, 201);
    if (method === "POST" && path.endsWith("/close")) {
      this.events[0] = { ...this.events[0], status: "closed", version: 3 };
      return this.json(route, this.events[0]);
    }
    if (method === "POST" && path === "/knowledge/query") {
      return this.json(route, { answer: "环境箱故障期间，相关环境试验步骤不得安排到故障窗口内。", evidence_available: true, citations: [{ standard_title: "CCC 环境试验规范", version: "2026.1", clause: "6.3", page: 18, content: "设备异常时应停止相关项目并评估已排任务。" }] });
    }
    if (method === "GET" && path === "/notifications") return this.json(route, pageResult(this.notifications));
    if (method === "PATCH" && path.endsWith("/read")) return route.fulfill({ status: 204 });
    if (method === "POST" && path === "/notification-drafts") return this.json(route, { draft_id: "draft-signed-not-01", notification_id: "NOT-01", source_hash: "not-01-v1", title: "环境箱 01 故障影响待处理订单", body: "环境箱 01 当前不可用于环境试验。", degraded: false });
    if (method === "POST" && path.startsWith("/notification-drafts/")) return this.json(route, { id: "DELIVERY-001", draft_id: "draft-signed-not-01", status: "accepted", accepted_at: at }, 202);
    if (method === "GET" && path === "/audit-logs") return this.json(route, pageResult(this.audit));
    if (method === "POST" && path === "/audit-logs/filter-suggestions") return this.json(route, { original_query: "查找今天与候选排程有关的记录", filters: [{ field: "action", operator: "contains", value: "schedule_preview" }], explanation: "已转换为可编辑过滤条件。", uncertainty: false, degraded: false });
    return this.json(route, {});
  }

  private json(route: Route, payload: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
  }
}

async function open(page: Page, api: BrowserApi, route: string) {
  await api.install(page);
  await gotoRoute(page, route);
  await expect(page.locator("#main-content")).toBeVisible();
}

async function gotoRoute(page: Page, route: string) {
  if (route === "/") return page.goto("http://127.0.0.1:4173/");
  const labels: Record<string, string> = {
    "/orders": "订单",
    "/resources": "资源",
    "/scheduling": "排程",
    "/execution": "执行",
    "/events": "事件",
    "/knowledge": "标准知识",
    "/notifications": "通知",
    "/admin/audit": "审计",
    "/admin/system": "系统状态",
  };
  await page.goto("http://127.0.0.1:4173/");
  await page.getByRole("link", { name: labels[route] }).click();
  await expect(page).toHaveURL(new RegExp(`${route}$`));
}

async function openProtectedRoute(page: Page, route: string) {
  await page.evaluate((target) => {
    window.history.pushState({}, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, route);
}

async function expectAxeClean(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious");
  expect(severe, severe.map((violation) => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
}

async function expectViewportIntegrity(page: Page) {
  const result = await page.evaluate(() => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const overflow = document.documentElement.scrollWidth > viewport.width + 1 || document.body.scrollWidth > viewport.width + 1;
    const controls = Array.from(document.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [role=button]"))
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0 && !element.classList.contains("skipLink");
      })
      .map((element) => ({ label: element.getAttribute("aria-label") || element.textContent?.trim() || element.tagName, scrollable: Boolean(element.closest("[class*='tableWrap']")), rect: element.getBoundingClientRect().toJSON() }));
    const outOfBounds = controls.filter(({ rect, scrollable }) => !scrollable && (rect.left < -1 || rect.top < -1 || rect.right > viewport.width + 1 || rect.bottom > viewport.height + 1));
    const overlaps: string[] = [];
    for (let index = 0; index < controls.length; index += 1) {
      for (let other = index + 1; other < controls.length; other += 1) {
        const first = controls[index];
        const second = controls[other];
        const width = Math.max(0, Math.min(first.rect.right, second.rect.right) - Math.max(first.rect.left, second.rect.left));
        const height = Math.max(0, Math.min(first.rect.bottom, second.rect.bottom) - Math.max(first.rect.top, second.rect.top));
        if (width * height > 4) overlaps.push(`${first.label} / ${second.label}`);
      }
    }
    return { overflow, outOfBounds, overlaps };
  });
  expect(result.overflow).toBeFalsy();
  expect(result.outOfBounds).toEqual([]);
  expect(result.overlaps).toEqual([]);
}

test("core browser workflow is server-confirmed across order, schedule, execution, incident, and knowledge", async ({ page }) => {
  const api = new BrowserApi("scheduler");
  await open(page, api, "/orders");
  await expect(page.getByRole("heading", { name: "订单", exact: true })).toBeVisible();
  await page.getByLabel("样品名称").fill("E2E 样品");
  await page.getByLabel("样品数量").fill("2");
  await page.getByLabel("承诺完成时间").fill("2026-07-16T17:00");
  await page.getByRole("checkbox", { name: "安全" }).check();
  await page.getByRole("button", { name: "创建订单" }).click();
  await expect(page.getByText("订单已创建，等待服务端排程。")).toBeVisible();

  await gotoRoute(page, "/scheduling");
  await expect(page.getByText("PRE-20260714-004")).toBeVisible();
  await page.getByRole("button", { name: "批准候选排程" }).click();
  await expect(page.getByRole("alert")).toContainText("候选排程已发生版本冲突");
  await page.getByRole("button", { name: "批准候选排程" }).click();
  await expect(page.getByText("候选排程已获批准，服务端已确认。")).toBeVisible();

  api.role = "operator";
  await gotoRoute(page, "/execution");
  await page.getByRole("button", { name: "开始 STEP-002" }).click();
  await expect(page.getByText("服务端已确认开始，步骤状态已更新。")).toBeVisible();

  api.role = "scheduler";
  await gotoRoute(page, "/events");
  await page.getByRole("button", { name: "查看 EVT-001" }).click();
  await page.getByRole("button", { name: "获取诊断" }).click();
  await expect(page.getByRole("heading", { name: "引用证据" })).toBeVisible();
  await page.getByRole("button", { name: "关闭异常诊断" }).click();
  await page.getByRole("button", { name: "人工关闭事件" }).click();
  await page.getByRole("button", { name: "确认关闭事件" }).click();
  await expect(page.getByText("事件已由服务端确认关闭。")).toBeVisible();

  await gotoRoute(page, "/knowledge");
  await page.getByLabel("标准问题").fill("环境箱异常如何处理？");
  await page.getByRole("button", { name: "查询标准" }).click();
  await expect(page.getByRole("heading", { name: "引用证据" })).toBeVisible();
  await expect(page.getByText("第 18 页")).toBeVisible();
});

test("contextual assistance remains bounded to explanation, editable drafts, and human-confirmed writes", async ({ page }) => {
  const api = new BrowserApi("scheduler");
  await open(page, api, "/scheduling");
  await page.getByRole("button", { name: "查看排程说明" }).click();
  await expect(page.getByRole("heading", { name: "排程说明" })).toBeVisible();
  await page.getByRole("button", { name: "排程前检查" }).click();
  await expect(page.getByText("环境箱 ENV-01 在维护窗口内不可用。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /重排|重新求解/ })).toHaveCount(0);

  await gotoRoute(page, "/events");
  await page.getByRole("button", { name: "查看 EVT-001" }).click();
  await page.getByRole("button", { name: "获取诊断" }).click();
  await expect(page.getByRole("dialog", { name: "异常诊断" })).toBeVisible();
  await page.getByRole("button", { name: "关闭异常诊断" }).click();
  await page.getByRole("button", { name: "人工关闭事件" }).click();
  await page.getByRole("button", { name: "确认关闭事件" }).click();
  await page.getByRole("button", { name: "异常案例候选" }).click();
  await expect(page.getByRole("dialog", { name: "异常案例候选" })).toBeVisible();
  await page.getByLabel("摘要").fill("已由人工复核的 ENV-01 异常摘要。");
  await page.getByRole("button", { name: "提交审核" }).click();
  await expect(page.getByText(/尚未进入长期记忆或检索结果/)).toBeVisible();

  await gotoRoute(page, "/admin/audit");
  await page.getByLabel("审计辅助检索问题").fill("查找今天与候选排程有关的记录");
  await page.getByRole("button", { name: "获取筛选建议" }).click();
  await expect(page.getByLabel("编辑筛选 action")).toHaveValue("schedule_preview");

  await gotoRoute(page, "/notifications");
  await page.getByRole("button", { name: "生成通知草稿" }).click();
  await page.getByLabel("编辑通知正文").fill("已人工编辑的通知正文");
  await page.getByRole("button", { name: "确认发送" }).click();
  await expect(page.getByText(/通知已由服务端接受发送/)).toBeVisible();
});

test("all four roles enforce route and action permissions", async ({ page }) => {
  const api = new BrowserApi("admin");
  await open(page, api, "/scheduling");
  await expect(page.getByRole("heading", { name: "排程工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "批准候选排程" })).toBeVisible();

  api.role = "scheduler";
  await gotoRoute(page, "/events");
  await expect(page.getByRole("heading", { name: "事件处置" })).toBeVisible();
  await page.getByRole("button", { name: "查看 EVT-001" }).click();
  await expect(page.getByRole("button", { name: "人工关闭事件" })).toBeVisible();

  api.role = "operator";
  await gotoRoute(page, "/execution");
  await expect(page.getByRole("heading", { name: "执行报告" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始 STEP-002" })).toBeVisible();
  await expect(page.getByRole("link", { name: "排程" })).toHaveCount(0);
  await openProtectedRoute(page, "/scheduling");
  await expect(page.getByRole("heading", { name: "无权访问此页面" })).toBeVisible();

  api.role = "viewer";
  await gotoRoute(page, "/orders");
  await expect(page.getByRole("heading", { name: "订单", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建订单" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "执行" })).toHaveCount(0);
  await openProtectedRoute(page, "/execution");
  await expect(page.getByRole("heading", { name: "无权访问此页面" })).toBeVisible();
});

test("key routes have no serious or critical axe violations and keep controls in the desktop viewport", async ({ page }) => {
  const api = new BrowserApi("scheduler");
  for (const route of ["/orders", "/scheduling", "/events", "/knowledge"]) {
    await open(page, api, route);
    await expectAxeClean(page);
    await expectViewportIntegrity(page);
  }
  api.role = "operator";
  await gotoRoute(page, "/execution");
  await expectAxeClean(page);
  await expectViewportIntegrity(page);
});

test("desktop product screenshots are captured at all required viewports", async ({ page }) => {
  const api = new BrowserApi("scheduler");
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await open(page, api, "/scheduling");
    await expectViewportIntegrity(page);
    await page.screenshot({ path: resolve(screenshotsDirectory, `scheduling-${viewport.width}x${viewport.height}.png`), fullPage: false });
  }
});
