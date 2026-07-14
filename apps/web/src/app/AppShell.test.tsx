import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "@/app/AppShell";
import type { Role } from "@/api/types";
import { useSessionStore } from "@/auth/sessionStore";

function renderShell(role: Role, displayName: string) {
  useSessionStore.setState({ session: { user_id: `${role}-001`, role, display_name: displayName } });

  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>总览内容</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
    useSessionStore.setState({ session: null });
  });

  it("shows the scheduler's session identity and available navigation", () => {
    renderShell("scheduler", "王调度");

    expect(screen.getByText("王调度")).toBeInTheDocument();
    expect(screen.getByText("scheduler")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "订单" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审计" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "执行" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("演示角色")).not.toBeInTheDocument();
  });

  it("hides navigation unavailable to an operator", () => {
    renderShell("operator", "陈工");

    expect(screen.getByText("陈工")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "执行" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "通知" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "订单" })).not.toBeInTheDocument();
    expect(screen.queryByText("管理")).not.toBeInTheDocument();
  });
});
