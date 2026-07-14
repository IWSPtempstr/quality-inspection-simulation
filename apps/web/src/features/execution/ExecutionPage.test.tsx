import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { ExecutionPage } from "@/features/execution/ExecutionPage";
import { server } from "@/mocks/server";
import { useSessionStore } from "@/auth/sessionStore";

function renderPage() {
  useSessionStore.setState({ session: { user_id: "operator-001", role: "operator", display_name: "陈工" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><ExecutionPage /></QueryClientProvider>);
}

describe("ExecutionPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());

  it("keeps a scheduled step unchanged until the start is confirmed by the server", async () => {
    server.use(http.patch("*/api/v1/schedule-steps/STEP-002/start", async () => {
      await delay(40);
      return HttpResponse.json({ id: "STEP-002", order_id: "ORD-20260714-001", project_id: "emc", equipment_id: "EMC-03", employee_ids: ["EMP-01"], starts_at: "2026-07-14T13:00:00+08:00", ends_at: "2026-07-14T16:00:00+08:00", status: "running", frozen: true, version: 4 });
    }));
    renderPage();

    const row = await screen.findByRole("row", { name: /STEP-002/ });
    expect(row).toHaveTextContent("已计划");
    fireEvent.click(screen.getByRole("button", { name: "开始 STEP-002" }));
    expect(row).toHaveTextContent("已计划");
    expect(screen.getByRole("button", { name: "开始 STEP-002" })).toHaveTextContent("等待服务端确认");
    await waitFor(() => expect(row).toHaveTextContent("进行中"));
    expect(screen.getByText(/服务端已确认开始/)).toHaveAttribute("role", "status");
  });

  it("shows a version conflict and lets the operator refresh the schedule", async () => {
    server.use(http.patch("*/api/v1/schedule-steps/STEP-002/start", () => HttpResponse.json({ title: "版本冲突", status: 409, detail: "步骤已被其他操作员更新" }, { status: 409 })));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "开始 STEP-002" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("执行步骤已发生版本冲突");
    expect(screen.getByRole("button", { name: "刷新当前排程" })).toBeEnabled();
  });

  it("reuses the caller idempotency key when retrying an execution report", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.patch("*/api/v1/schedule-steps/STEP-002/start", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({ title: "暂时不可用", status: 500 }, { status: 500 });
      return HttpResponse.json({ id: "STEP-002", order_id: "ORD-20260714-001", project_id: "emc", equipment_id: "EMC-03", employee_ids: ["EMP-01"], starts_at: "2026-07-14T13:00:00+08:00", ends_at: "2026-07-14T16:00:00+08:00", status: "running", frozen: true, version: 4 });
    }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "开始 STEP-002" }));
    const reportError = await screen.findByRole("alert");
    fireEvent.click(within(reportError).getByRole("button", { name: "重试" }));

    await waitFor(() => expect(screen.getByText(/服务端已确认开始/)).toBeInTheDocument());
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe("");
    expect(keys[1]).toBe(keys[0]);
  });
});
