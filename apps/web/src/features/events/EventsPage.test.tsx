import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { EventsPage } from "@/features/events/EventsPage";
import { server } from "@/mocks/server";
import { useSessionStore } from "@/auth/sessionStore";

function renderPage() {
  useSessionStore.setState({ session: { user_id: "scheduler-001", role: "scheduler", display_name: "王调度" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><EventsPage /></QueryClientProvider>);
}

describe("EventsPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());

  it("opens the event-scoped diagnosis drawer with cited evidence after the server responds", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看 EVT-001" }));
    fireEvent.click(await screen.findByRole("button", { name: "获取诊断" }));
    expect(await screen.findByRole("dialog", { name: "异常诊断" })).toBeInTheDocument();
    expect(await screen.findByText("CCC 环境试验规范")).toBeInTheDocument();
    expect(screen.getByText("保持运行中步骤冻结")).toBeInTheDocument();
    expect(screen.getByText("诊断仅供人工判断，不会执行排程或变更资源。", { selector: "p" })).toBeInTheDocument();
  });

  it("sends the event version for human close-out and recovers from a conflict", async () => {
    let ifMatch = "";
    server.use(http.post("*/api/v1/events/EVT-001/close", ({ request }) => {
      ifMatch = request.headers.get("If-Match") ?? "";
      return HttpResponse.json({ title: "版本冲突", status: 409, detail: "事件已由其他调度员更新" }, { status: 409 });
    }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看 EVT-001" }));
    fireEvent.click(await screen.findByRole("button", { name: "人工关闭事件" }));
    const dialog = await screen.findByRole("alertdialog", { name: "关闭事件 EVT-001" });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认关闭事件" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("事件已发生版本冲突");
    expect(ifMatch).toBe("2");
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新事件信息" })).toBeEnabled());
  });

  it("reuses the caller idempotency key when retrying a diagnosis request", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.post("*/api/v1/events/EVT-001/diagnose", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({ title: "暂时不可用", status: 500 }, { status: 500 });
      return HttpResponse.json({ event_id: "EVT-001", affected_order_ids: [], sla_risks: [], evidence: [], recommendations: [], evidence_gaps: [], confidence: "insufficient" });
    }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看 EVT-001" }));
    fireEvent.click(await screen.findByRole("button", { name: "获取诊断" }));
    fireEvent.click(await screen.findByRole("button", { name: "重试获取诊断" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "异常诊断" })).toBeInTheDocument());
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe("");
    expect(keys[1]).toBe(keys[0]);
  });

  it("reuses the caller idempotency key when retrying a human close-out", async () => {
    const keys: string[] = [];
    let attempts = 0;
    server.use(http.post("*/api/v1/events/EVT-001/close", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({ title: "暂时不可用", status: 500 }, { status: 500 });
      return HttpResponse.json({ id: "EVT-001", event_type: "设备异常", entity_id: "EMC-03", occurred_at: "2026-07-14T09:15:00+08:00", severity: "high", status: "closed", payload: {}, version: 3 });
    }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看 EVT-001" }));
    fireEvent.click(await screen.findByRole("button", { name: "人工关闭事件" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "确认关闭事件" }));
    fireEvent.click(await screen.findByRole("button", { name: "重试关闭事件" }));

    await waitFor(() => expect(screen.getByText(/事件已由服务端确认关闭/)).toBeInTheDocument());
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe("");
    expect(keys[1]).toBe(keys[0]);
  });

  it("traps dialog focus, closes on escape, and returns focus to the close trigger", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "查看 EVT-001" }));
    const closeTrigger = await screen.findByRole("button", { name: "人工关闭事件" });
    fireEvent.click(closeTrigger);
    const dialog = await screen.findByRole("alertdialog", { name: "关闭事件 EVT-001" });
    const confirm = within(dialog).getByRole("button", { name: "确认关闭事件" });
    const cancel = within(dialog).getByRole("button", { name: "取消" });
    const dismiss = within(dialog).getByRole("button", { name: "取消关闭" });

    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(dismiss).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(closeTrigger).toHaveFocus();
    expect(cancel).not.toBeInTheDocument();
  });
});
