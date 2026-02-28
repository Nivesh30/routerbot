import { test, expect } from "@playwright/test";

test.describe("Logs Page", () => {
  test("renders audit logs page", async ({ page }) => {
    await page.goto("/ui/logs");

    await expect(
      page.getByRole("heading", { name: "Audit Logs" }),
    ).toBeVisible();
  });

  test("has refresh button", async ({ page }) => {
    await page.goto("/ui/logs");

    await expect(
      page.getByRole("button", { name: "Refresh" }),
    ).toBeVisible();
  });

  test("has filter inputs", async ({ page }) => {
    await page.goto("/ui/logs");

    await expect(
      page.getByRole("textbox", { name: /actor/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: /action/i }),
    ).toBeVisible();
  });

  test("shows empty state or log entries", async ({ page }) => {
    await page.goto("/ui/logs");

    const empty = page.getByText("No audit logs");
    const table = page.getByRole("table");
    await expect(empty.or(table)).toBeVisible();
  });
});
