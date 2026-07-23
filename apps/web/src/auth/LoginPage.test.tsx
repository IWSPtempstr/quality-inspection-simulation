import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { LoginPage } from "@/auth/LoginPage";

describe("LoginPage", () => {
  afterEach(() => {
    cleanup();
  });

  it("explains an expired session without exposing credentials or a role selector", () => {
    render(<MemoryRouter initialEntries={["/login?return_to=%2Forders&reason=expired"]}><LoginPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "登录会话已结束" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "使用企业账号登录" })).toBeInTheDocument();
    expect(screen.queryByLabelText("演示角色")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/密码|令牌/)).not.toBeInTheDocument();
  });

  it("shows a clear retry state when the callback cannot be completed", () => {
    render(<MemoryRouter initialEntries={["/login?reason=callback_failed"]}><LoginPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "登录未完成" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "使用企业账号登录" })).toBeInTheDocument();
  });
});
