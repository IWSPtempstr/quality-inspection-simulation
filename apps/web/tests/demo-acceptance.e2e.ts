import { expect, test } from "@playwright/test";

test("demo mode loads fixture data and limits navigation after a role switch", async ({ page }) => {
  await page.goto("http://127.0.0.1:5174/");
  await expect(page.getByLabel("演示角色")).toHaveValue("scheduler");
  await expect(page.getByText("王调度")).toBeVisible();

  await page.getByRole("link", { name: "订单" }).click();
  await expect(page.getByRole("heading", { name: "订单", exact: true })).toBeVisible();
  await expect(page.getByText("空气炸锅 A8")).toBeVisible();

  await page.getByLabel("演示角色").selectOption("operator");
  await expect(page.getByText("演示操作员")).toBeVisible();
  await expect(page.getByRole("link", { name: "订单" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "执行" })).toBeVisible();
});
