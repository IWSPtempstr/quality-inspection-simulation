import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { OrdersPage } from "@/features/orders/OrdersPage";
import { useSessionStore } from "@/auth/sessionStore";
import { server } from "@/mocks/server";

function renderPage(role: "admin" | "scheduler" | "viewer" = "scheduler") {
  useSessionStore.setState({ session: { user_id: "test-user", role, display_name: "测试用户" } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><OrdersPage /></QueryClientProvider>);
}

async function openEditor() {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "编辑 ORD-20260714-001" }));
  return screen.findByRole("dialog", { name: "编辑订单" });
}

function fillCreateForm() {
  fireEvent.change(screen.getByLabelText("样品名称"), { target: { value: "幂等样品" } });
  fireEvent.change(screen.getByLabelText("承诺完成时间"), { target: { value: "2026-07-16T09:00" } });
  fireEvent.click(screen.getByLabelText("安全"));
}

describe("OrdersPage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); useSessionStore.setState({ session: null }); });
  afterAll(() => server.close());
  beforeEach(() => server.resetHandlers());

  it("keeps viewers read-only while still showing orders", async () => {
    renderPage("viewer");

    expect(await screen.findByText("空气炸锅 A8")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "创建订单" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑 ORD-20260714-001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "复测 ORD-20260714-001" })).not.toBeInTheDocument();
  });

  it("shows deterministic data-quality findings without auto-correcting the order", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "数据质量预检" }));
    expect(await screen.findByRole("heading", { name: "订单预检" })).toBeInTheDocument();
    expect(screen.getByText(/存在阻塞规则，不能由助手自动修正/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建订单" })).toBeEnabled();
  });

  it("confirms an order edit with the server before closing the dialog", async () => {
    const dialog = await openEditor();
    fireEvent.change(within(dialog).getByLabelText("订单优先级"), { target: { value: "urgent" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑订单" })).not.toBeInTheDocument());
  });

  it("keeps the edit dialog open and offers a reload when the version conflicts", async () => {
    server.use(http.patch("*/api/v1/orders/:id", () => HttpResponse.json({ title: "版本冲突", status: 409, detail: "订单已被其他操作更新" }, { status: 409, headers: { "Content-Type": "application/problem+json" } })));
    const dialog = await openEditor();
    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));
    expect(await within(dialog).findByText(/订单版本已过期/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "重新加载服务器版本" })).toBeInTheDocument();
  });

  it("creates a retest only after a reason is provided and accepted by the server", async () => {
    renderPage();
    await screen.findByText("空气炸锅 A8");
    fireEvent.click(screen.getByRole("button", { name: "复测 ORD-20260714-001" }));
    fireEvent.change(screen.getByLabelText("复测原因"), { target: { value: "结果异常" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发起复测" }));
    expect(await screen.findByText("复测订单已创建，等待服务端排程。", { selector: "p" })).toBeInTheDocument();
  });

  it("reuses a create key after failure and issues a fresh key for the next creation", async () => {
    const keys: string[] = [];
    server.use(http.post("*/api/v1/orders", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      if (keys.length === 1) return HttpResponse.json({ title: "暂时不可用", status: 503 }, { status: 503 });
      return HttpResponse.json({ id: `ORD-KEY-${keys.length}` }, { status: 201 });
    }));
    renderPage();
    await screen.findByRole("button", { name: "创建订单" });

    fillCreateForm();
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    await screen.findByText("订单已创建，等待服务端排程。", { selector: "p" });

    fillCreateForm();
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[1]);
  });

  it("reuses an edit key after a failed save", async () => {
    const keys: string[] = [];
    server.use(http.patch("*/api/v1/orders/:id", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      if (keys.length === 1) return HttpResponse.json({ title: "暂时不可用", status: 503 }, { status: 503 });
      return HttpResponse.json({ id: "ORD-20260714-001" });
    }));
    const dialog = await openEditor();

    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));
    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("reuses a retest key after a failed submission", async () => {
    const keys: string[] = [];
    server.use(http.post("*/api/v1/orders/:id/retests", ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      if (keys.length === 1) return HttpResponse.json({ title: "暂时不可用", status: 503 }, { status: 503 });
      return HttpResponse.json({ id: "ORD-20260714-001-RETEST" }, { status: 201 });
    }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "复测 ORD-20260714-001" }));
    fireEvent.change(screen.getByLabelText("复测原因"), { target: { value: "结果异常" } });

    fireEvent.click(screen.getByRole("button", { name: "确认发起复测" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认发起复测" }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).toBe(keys[0]);
  });
});
