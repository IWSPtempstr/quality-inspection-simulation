import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { ResourcesPage } from "@/features/resources/ResourcesPage";
import { server } from "@/mocks/server";
import { useSessionStore } from "@/auth/sessionStore";

function renderPage() {
  useSessionStore.setState({ session: { user_id: "scheduler-001", role: "scheduler", display_name: "王调度" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><ResourcesPage /></QueryClientProvider>);
}

describe("ResourcesPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());

  it("loads the equipment, employee, shift, and unavailability surfaces", async () => {
    renderPage();

    expect(await screen.findByText("EMC 暗室 03")).toBeInTheDocument();
    expect(screen.getByText("陈工")).toBeInTheDocument();
    expect(screen.getByText("白班")).toBeInTheDocument();
    expect(screen.getByText("计划维护")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "资源服务提示" })).toHaveTextContent("部分辅助服务降级");
  });

  it("shows a surface error and retries only that surface", async () => {
    let attempts = 0;
    server.use(http.get("*/api/v1/resources/equipment", () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ title: "服务不可用", status: 503 }, { status: 503 })
        : HttpResponse.json([{ id: "SAFE-02", name: "安全测试台 02", status: "available", capacity: 2, project_ids: ["safety"], version: 8 }]);
    }));
    renderPage();

    const equipment = screen.getByRole("region", { name: "设备" });
    expect(await within(equipment).findByText("无法加载设备。请检查网络后重试。")).toBeInTheDocument();
    fireEvent.click(within(equipment).getByRole("button", { name: "重试加载设备" }));
    await waitFor(() => expect(within(equipment).getByText("安全测试台 02")).toBeInTheDocument());
    expect(attempts).toBe(2);
  });

  it("shows resource preflight findings without changing resource records", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "检查资源数据" }));
    expect(await screen.findByText(/环境箱 ENV-01 在维护窗口内不可用/)).toBeInTheDocument();
    expect(screen.getByText("EMC 暗室 03")).toBeInTheDocument();
  });
});
