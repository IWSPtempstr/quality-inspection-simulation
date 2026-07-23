import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

const expectedRoutes = [
  ["/", "总览"],
  ["/orders", "订单"],
  ["/resources", "资源"],
  ["/scheduling", "排程工作台"],
  ["/execution", "执行报告"],
  ["/events", "事件处置"],
  ["/knowledge", "标准知识"],
  ["/notifications", "通知"],
  ["/admin/audit", "审计"],
  ["/admin/system", "系统状态"],
] as const;

async function renderRoute(path: string) {
  vi.stubEnv("VITE_PUBLIC_SHOWCASE", "true");
  vi.resetModules();
  window.location.hash = `#${path}`;
  const { PublicShowcaseApp } = await import("@/showcase/PublicShowcaseApp");
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><PublicShowcaseApp /></QueryClientProvider>);
}

describe("PublicShowcaseApp", () => {
  afterEach(() => {
    cleanup();
    window.location.hash = "";
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("publishes exactly the public workbench routes required by the showcase contract", async () => {
    vi.stubEnv("VITE_PUBLIC_SHOWCASE", "true");
    vi.resetModules();
    const { SHOWCASE_WORKBENCH_ROUTES } = await import("@/showcase/PublicShowcaseApp");
    expect(SHOWCASE_WORKBENCH_ROUTES).toEqual(expectedRoutes.map(([path]) => path));
  });

  it.each(expectedRoutes)("renders %s through the hash router with fixed display access", async (path, pageName) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await renderRoute(path);

    expect(await screen.findByRole("heading", { name: pageName })).toBeInTheDocument();
    expect(screen.getByText("公开产品展示")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /登录/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("演示角色")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
