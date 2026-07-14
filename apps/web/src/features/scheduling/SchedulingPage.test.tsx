import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { SchedulingPage } from "@/features/scheduling/SchedulingPage";
import { server } from "@/mocks/server";
import { useSessionStore } from "@/auth/sessionStore";

function renderPage(role: "admin" | "scheduler" | "viewer" = "scheduler") {
  useSessionStore.setState({ session: { user_id: "test-user", role, display_name: "测试用户" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><SchedulingPage /></QueryClientProvider>);
}

describe("SchedulingPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());

  it("shows the server schedule, frozen step, candidate metrics, and SLA fallback label", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("SLA 兜底")).toBeInTheDocument();
    expect(screen.getByText("运行中，已冻结")).toBeInTheDocument();
    expect(screen.getByText("加权延误")).toBeInTheDocument();
    const metrics = screen.getByRole("list", { name: "候选排程指标" });
    expect(metrics.querySelectorAll(":scope > li")).toHaveLength(6);
    expect(container.querySelector("dl")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "当前排程甘特图" })).toHaveTextContent("STEP-002");
    expect(screen.getByRole("button", { name: "批准候选排程" })).toBeEnabled();
  });

  it("shows fallback context and reported blockers before a reviewer decides", async () => {
    renderPage();

    expect(await screen.findByRole("status", { name: "候选采用 SLA 兜底排程" })).toHaveTextContent("CP-SAT 未在时限内找到可行解");
    expect(screen.getByText("cp_sat_timeout_without_feasible_solution")).toBeInTheDocument();
    const blockers = screen.getByRole("list", { name: "候选排程阻塞项" });
    expect(blockers).toHaveTextContent("STEP-003");
    expect(blockers).toHaveTextContent("ORD-20260713-018");
    expect(blockers).toHaveTextContent("环境箱 ENV-01 在维护窗口内不可用");
  });

  it("shows an explanation and deterministic preflight without exposing a rebuild action", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看排程说明" }));
    expect(await screen.findByText(/候选保持运行中的安全步骤冻结/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重排|重新求解/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "排程前检查" }));
    expect(await screen.findByRole("heading", { name: "排程前检查" })).toBeInTheDocument();
    expect(screen.getByText("环境箱 ENV-01 在维护窗口内不可用。", { exact: true })).toBeInTheDocument();
  });

  it("keeps approval unavailable to a read-only role", async () => {
    renderPage("viewer");

    expect(await screen.findByText(/候选排程为只读/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "批准候选排程" })).not.toBeInTheDocument();
  });

  it("announces approval only after the server confirms it", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "批准候选排程" }));

    expect(await screen.findByText(/候选排程已获批准/)).toHaveAttribute("role", "status");
  });

  it("recovers from a stale approval version by refreshing the candidate", async () => {
    server.use(http.post("*/api/v1/schedule-previews/PRE-20260714-004/approve", () => HttpResponse.json({ title: "版本冲突", status: 409, detail: "候选排程已被其他调度员处理" }, { status: 409 })));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "批准候选排程" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("候选排程已发生版本冲突");
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新候选排程" })).toBeInTheDocument());
  });

  it("reuses one idempotency key when an approval is retried", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.post("*/api/v1/schedule-previews/PRE-20260714-004/approve", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({ title: "服务暂不可用", status: 503, detail: "请重试" }, { status: 503 });
      return HttpResponse.json({ id: "PRE-20260714-004", status: "approved", algorithm_used: "sla_fallback", solver_status: "timeout_without_feasible_solution", fallback_used: true, fallback_reason: "cp_sat_timeout_without_feasible_solution", base_schedule_version: 12, resource_snapshot_version: 38, frozen_step_count: 1, changed_step_count: 2, delayed_order_count: 1, weighted_delay_minutes: 240, total_delay_minutes: 90, blockers: [], changes: [], schedule: { version: 13, steps: [] }, version: 1 });
    }));
    renderPage();

    const approve = await screen.findByRole("button", { name: "批准候选排程" });
    fireEvent.click(approve);
    expect(await screen.findByText(/操作未完成/)).toBeInTheDocument();
    fireEvent.click(approve);

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("reuses one idempotency key when a rejection is retried", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.post("*/api/v1/schedule-previews/PRE-20260714-004/reject", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({ title: "服务暂不可用", status: 503, detail: "请重试" }, { status: 503 });
      return HttpResponse.json({ id: "PRE-20260714-004", status: "rejected", algorithm_used: "sla_fallback", solver_status: "timeout_without_feasible_solution", fallback_used: true, fallback_reason: "cp_sat_timeout_without_feasible_solution", base_schedule_version: 12, resource_snapshot_version: 38, frozen_step_count: 1, changed_step_count: 2, delayed_order_count: 1, weighted_delay_minutes: 240, total_delay_minutes: 90, blockers: [], changes: [], schedule: { version: 13, steps: [] }, version: 1 });
    }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "拒绝候选排程" }));
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }));
    expect(await screen.findByText(/操作未完成/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "拒绝候选排程" }));
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }));

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("keeps reject confirmation modal focus contained and restores the trigger on Escape", async () => {
    renderPage();

    const reject = await screen.findByRole("button", { name: "拒绝候选排程" });
    fireEvent.click(reject);

    const dialog = screen.getByRole("alertdialog");
    const cancel = screen.getByRole("button", { name: "取消" });
    const confirm = screen.getByRole("button", { name: "确认拒绝" });
    expect(document.activeElement).toBe(confirm);
    expect(screen.getByRole("button", { name: "批准候选排程" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(reject);
  });
});
