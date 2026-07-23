import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionGate } from "@/app/router";
import { clearCsrfToken } from "@/api/client";
import { useSessionStore } from "@/auth/sessionStore";

function LocationProbe() { return <p data-testid="location">{useLocation().pathname}{useLocation().search}</p>; }

function renderGate(response: Response) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/orders?status=open"]}>
        <Routes>
          <Route element={<SessionGate />}><Route path="/orders" element={<p>订单</p>} /></Route>
          <Route path="/login" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionGate", () => {
  afterEach(() => {
    cleanup();
    clearCsrfToken();
    useSessionStore.setState({ session: null });
    vi.unstubAllGlobals();
  });

  it("redirects a confirmed 401 session failure to login and preserves the local destination", async () => {
    renderGate(new Response(JSON.stringify({ status: 401, title: "未登录" }), { status: 401 }));

    expect(await screen.findByTestId("location")).toHaveTextContent("/login?return_to=%2Forders%3Fstatus%3Dopen&reason=expired");
  });

  it("keeps a 503 session failure on the operational retry state", async () => {
    renderGate(new Response(JSON.stringify({ status: 503, title: "服务暂不可用" }), { status: 503 }));

    expect(await screen.findByRole("heading", { name: "服务暂不可用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
  });
});
