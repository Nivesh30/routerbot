import { test, expect } from "@playwright/test";

test.describe("Guardrails Page", () => {
  test("renders all guardrails", async ({ page }) => {
    await page.goto("/ui/guardrails");

    await expect(
      page.getByRole("heading", { name: "Guardrails" }),
    ).toBeVisible();

    // All 5 guardrails should be listed
    const guardrails = [
      "Secret Detection",
      "PII Detection",
      "Content Moderation",
      "Banned Keywords",
      "Blocked Users",
    ];

    for (const name of guardrails) {
      await expect(
        page.getByRole("heading", { name, level: 3 }),
      ).toBeVisible();
    }
  });

  test("shows enabled/disabled status", async ({ page }) => {
    await page.goto("/ui/guardrails");

    // Secret Detection and PII should be enabled
    const statuses = page.getByText(/^(Enabled|Disabled)$/);
    expect(await statuses.count()).toBeGreaterThanOrEqual(5);
  });

  test("has configure buttons for each guardrail", async ({ page }) => {
    await page.goto("/ui/guardrails");

    const configureButtons = page.getByRole("button", { name: "Configure" });
    expect(await configureButtons.count()).toBe(5);
  });

  test("shows priority numbers", async ({ page }) => {
    await page.goto("/ui/guardrails");

    for (let i = 1; i <= 5; i++) {
      await expect(page.getByText(`Priority ${i}`)).toBeVisible();
    }
  });
});
