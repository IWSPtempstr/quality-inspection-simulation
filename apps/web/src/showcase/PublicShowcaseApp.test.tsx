import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicShowcaseApp, SHOWCASE_WORKBENCH_ROUTES } from "@/showcase/PublicShowcaseApp";

const expectedRoutes = [
  ["/", "总览"],
  ["/orders", "订单"],
  ["/resources", "资源"],
  ["/scheduling", "排程"],
  ["/execution", "执行"],
  ["/events", "事件"],
  ["/knowledge", "标准知识"],
  ["/notifications", "通知"],
  ["/admin/audit", "审计"],
  ["/admin/system", "系统状态"],
] as const;

function renderRoute(path: string) {
  window.location.hash = `#${path}`;
  return render(<PublicShowcaseApp />);
}

describe("PublicShowcaseApp", () => {
  afterEach(() => {
    cleanup();
    window.location.hash = "";
    vi.unstubAllGlobals();
  });

  it("publishes exactly the public workbench routes required by the showcase contract", () => {
    expect(SHOWCASE_WORKBENCH_ROUTES).toEqual(expectedRoutes.map(([path]) => path));
  });

  it.each(expectedRoutes)("renders %s through the hash router with fixed display access", async (path, pageName) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(path);

    expect(await screen.findByRole("heading", { name: pageName })).toBeInTheDocument();
    expect(screen.getByText("公开产品展示")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /登录/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("演示角色")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
