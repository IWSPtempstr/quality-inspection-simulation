import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { AuditPage } from "@/features/admin/AuditPage";
import { SystemPage } from "@/features/admin/SystemPage";
import { server } from "@/mocks/server";

function renderPage(page: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>);
}

describe("admin management pages", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); });
  afterAll(() => server.close());

  it("shows a read-only audit trail and retries a failed load", async () => {
    let attempts = 0;
    server.use(http.get("*/api/v1/audit-logs", () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ title: "服务不可用", status: 503 }, { status: 503 })
        : HttpResponse.json({ items: [{ id: "AUD-02", actor_id: "scheduler-001", action: "schedule_preview_created", created_at: "2026-07-14T09:00:00+08:00", detail: { preview_id: "PRE-01" } }], page: 1, page_size: 25, total: 1 });
    }));
    renderPage(<AuditPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载审计记录");
    fireEvent.click(screen.getByRole("button", { name: "重试加载审计记录" }));
    await waitFor(() => expect(screen.getByText("schedule_preview_created")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /删除|编辑|导出/ })).not.toBeInTheDocument();
  });

  it("shows actionable degraded service state without control actions", async () => {
    renderPage(<SystemPage />);

    expect(await screen.findByRole("status")).toHaveTextContent("部分服务降级");
    expect(screen.getByText("chroma")).toBeInTheDocument();
    expect(screen.getByText("降级")).toBeInTheDocument();
    expect(screen.getByText("标准查询可能证据不足")).toBeInTheDocument();
  });

  it("keeps audit assistance as editable filters instead of changing audit records", async () => {
    renderPage(<AuditPage />);

    fireEvent.change(await screen.findByRole("textbox", { name: "审计辅助检索问题" }), { target: { value: "查找今天与候选排程有关的记录" } });
    fireEvent.click(screen.getByRole("button", { name: "获取筛选建议" }));
    expect(await screen.findByDisplayValue("schedule_preview")).toBeInTheDocument();
    expect(screen.getByText("筛选建议不会修改、删除或补写审计记录。", { exact: true })).toBeInTheDocument();
  });
});
