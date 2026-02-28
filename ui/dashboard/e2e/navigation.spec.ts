import { test, expect } from "@playwright/test";

/**
 * Smoke test: Click every sidebar link and verify the page renders
 * without errors (no blank page, no crash).
 */
test.describe("Navigation Smoke", () => {
  const pages = [
    { name: "Dashboard", path: "/ui", heading: /Dashboard/i },
    { name: "Models", path: "/ui/models", heading: /Models/i },
    { name: "Keys", path: "/ui/keys", heading: /Virtual Keys/i },
    { name: "Teams", path: "/ui/teams", heading: /Teams/i },
    { name: "Users", path: "/ui/users", heading: /Users/i },
    { name: "Spend", path: "/ui/spend", heading: /Spend Analytics/i },
    { name: "Guardrails", path: "/ui/guardrails", heading: /Guardrails/i },
    { name: "Logs", path: "/ui/logs", heading: /Audit Logs/i },
    { name: "Settings", path: "/ui/settings", heading: /Settings/i },
  ];

  for (const { name, path, heading } of pages) {
    test(`navigates to ${name}`, async ({ page }) => {
      await page.goto(path);

      // Page should have the expected heading
      await expect(
        page.getByRole("heading", { name: heading, level: 1 }),
      ).toBeVisible({ timeout: 10_000 });

      // No JS errors — check the page isn't completely blank
      const body = page.locator("body");
      const text = await body.textContent();
      expect(text?.length).toBeGreaterThan(50);
    });
  }

  test("sidebar navigation works via clicks", async ({ page }) => {
    await page.goto("/ui");

    // Click through each nav link
    for (const { name, heading } of pages.slice(1)) {
      await page.getByRole("link", { name }).click();
      await expect(
        page.getByRole("heading", { name: heading, level: 1 }),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});
