import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("workspace renders and captures a UI review screenshot", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "跨教材知识结构" })).toBeVisible();
  await expect(page.locator(".upload-zone").getByText("上传教材", { exact: true })).toBeVisible();
  await expect(page.getByText("图谱编码")).toBeVisible();
  await expect(page.getByRole("button", { name: /构建图谱/ })).toBeVisible();

  mkdirSync("artifacts/screenshots", { recursive: true });
  await page.screenshot({
    path: "artifacts/screenshots/workspace-1440x900.png",
    fullPage: true,
  });
});

test("api health is reachable from the frontend test run", async ({ request }) => {
  const response = await request.get("http://127.0.0.1:8000/api/health");
  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  expect(data.status).toBe("ok");
});
