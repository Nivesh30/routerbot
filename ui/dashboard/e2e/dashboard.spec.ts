import { test, expect } from "@playwright/test";

test.describe("Dashboard", () => {
  test("renders main metrics and nav", async ({ page }) => {
    await page.goto("/ui");

    // Page title
    await expect(page).toHaveTitle(/RouterBot/);

    // Sidebar nav links
    const nav = page.getByRole("navigation").first();
    for (const label of [
      "Dashboard",
      "Models",
      "Keys",
      "Teams",
      "Users",
      "Spend",
      "Guardrails",
      "Logs",
      "Settings",
    ]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }

    // Metric cards
    await expect(page.getByText("Requests (24h)")).toBeVisible();
    await expect(page.getByText("Active Models")).toBeVisible();
  });

  test("header shows user info and logout", async ({ page }) => {
    await page.goto("/ui");
    await expect(page.getByText("master")).toBeVisible();
    await expect(page.getByText("admin")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Logout" }),
    ).toBeVisible();
  });
});
