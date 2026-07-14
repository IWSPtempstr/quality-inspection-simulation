import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { server } from "@/mocks/server";
import { useSessionStore } from "@/auth/sessionStore";

function renderPage() {
  useSessionStore.setState({ session: { user_id: "scheduler-001", role: "scheduler", display_name: "王调度" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><NotificationsPage /></QueryClientProvider>);
}

describe("NotificationsPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());

  it("keeps a notification unread until the server confirms the read action", async () => {
    server.use(http.patch("*/api/v1/notifications/NOT-01/read", async () => {
      await delay(40);
      return new HttpResponse(null, { status: 204 });
    }));
    renderPage();

    const item = await screen.findByRole("listitem", { name: /环境箱 01 故障影响待处理订单/ });
    fireEvent.click(within(item).getByRole("button", { name: "标记为已读 NOT-01" }));
    expect(item).toHaveTextContent("未读");
    expect(within(item).getByRole("button", { name: "标记为已读 NOT-01" })).toHaveTextContent("等待服务端确认");
    await waitFor(() => expect(item).toHaveTextContent("已读"));
    expect(screen.getByRole("status")).toHaveTextContent("服务端已确认通知已读");
  });

  it("reuses an idempotency key when a failed read action is retried", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.patch("*/api/v1/notifications/NOT-01/read", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ title: "版本冲突", status: 409, detail: "通知状态已改变" }, { status: 409 })
        : new HttpResponse(null, { status: 204 });
    }));
    renderPage();

    const item = await screen.findByRole("listitem", { name: /环境箱 01 故障影响待处理订单/ });
    fireEvent.click(within(item).getByRole("button", { name: "标记为已读 NOT-01" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("通知状态已发生冲突");
    expect(item).toHaveTextContent("未读");
    fireEvent.click(screen.getByRole("button", { name: "重试标记已读 NOT-01" }));

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    await waitFor(() => expect(item).toHaveTextContent("已读"));
  });

  it("keeps notification enhancement as an editable draft until the user confirms sending", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "生成通知草稿" }));
    const body = await screen.findByRole("textbox", { name: "编辑通知正文" });
    expect((body as HTMLTextAreaElement).value).toContain("环境箱 01");
    fireEvent.change(body, { target: { value: "已人工编辑的通知正文" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发送" }));
    expect(await screen.findByRole("status")).toHaveTextContent("通知已由服务端接受发送");
  });
});
