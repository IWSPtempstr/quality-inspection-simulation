import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { KnowledgePage } from "@/features/knowledge/KnowledgePage";
import { server } from "@/mocks/server";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><KnowledgePage /></QueryClientProvider>);
}

describe("KnowledgePage", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { cleanup(); server.resetHandlers(); });
  afterAll(() => server.close());

  it("renders a standards answer only with complete source citations", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("标准问题"), { target: { value: "环境箱故障期间如何安排？" } });
    fireEvent.click(screen.getByRole("button", { name: "查询标准" }));

    expect(await screen.findByText("CCC 环境试验规范")).toBeInTheDocument();
    expect(screen.getByText("版本 2026.1 | 条款 6.3 | 第 18 页")).toBeInTheDocument();
    expect(screen.getByText("设备异常时应停止相关项目并评估已排任务。", { exact: true })).toBeInTheDocument();
  });

  it("withholds an uncited conclusion and explicitly reports insufficient evidence", async () => {
    server.use(http.post("*/api/v1/knowledge/query", () => HttpResponse.json({ answer: "不应展示的结论", citations: [], evidence_available: true })));
    renderPage();

    fireEvent.change(screen.getByLabelText("标准问题"), { target: { value: "没有证据的问题" } });
    fireEvent.click(screen.getByRole("button", { name: "查询标准" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("证据不足");
    expect(screen.queryByText("不应展示的结论")).not.toBeInTheDocument();
  });

  it("retries a failed impact analysis with the requested standard version", async () => {
    let attempts = 0;
    let versionId = "";
    server.use(http.post("*/api/v1/knowledge/impact-analysis", async ({ request }) => {
      attempts += 1;
      versionId = (await request.json() as { standard_version_id: string }).standard_version_id;
      return attempts === 1
        ? HttpResponse.json({ title: "服务不可用", status: 503 }, { status: 503 })
        : HttpResponse.json({ answer: "版本变更会影响环境试验安排。", citations: [{ standard_title: "CCC 环境试验规范", version: "2026.2", clause: "6.3", page: 18, content: "设备异常时应停止相关项目。" }], evidence_available: true });
    }));
    renderPage();

    fireEvent.change(screen.getByLabelText("标准版本标识"), { target: { value: "CCC-2026.2" } });
    fireEvent.click(screen.getByRole("button", { name: "分析影响" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法完成影响分析");
    fireEvent.click(screen.getByRole("button", { name: "重试影响分析" }));
    await waitFor(() => expect(screen.getByText("版本变更会影响环境试验安排。")).toBeInTheDocument());
    expect(versionId).toBe("CCC-2026.2");
  });
});
