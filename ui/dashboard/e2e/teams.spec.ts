import { test, expect } from "@playwright/test";

test.describe("Teams Page", () => {
  test("renders teams page", async ({ page }) => {
    await page.goto("/ui/teams");

    await expect(page.getByRole("heading", { name: "Teams" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "New Team" }).first(),
    ).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Search teams" })).toBeVisible();
  });

  test("create team modal opens with form fields", async ({ page }) => {
    await page.goto("/ui/teams");

    await page.getByRole("button", { name: "New Team" }).first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Create Team" }),
    ).toBeVisible();

    // Form fields
    await expect(
      dialog.getByRole("textbox", { name: "Team name" }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("spinbutton", { name: "Budget limit" }),
    ).toBeVisible();
    // Allowed models: either checkbox chips (when models loaded) or textbox fallback
    await expect(dialog.getByText("Allowed models")).toBeVisible();

    // Cancel
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("can create a team", async ({ page }) => {
    await page.goto("/ui/teams");

    await page.getByRole("button", { name: "New Team" }).first().click();
    const dialog = page.getByRole("dialog");

    const teamName = `Test Team ${Date.now()}`;
    await dialog
      .getByRole("textbox", { name: "Team name" })
      .fill(teamName);
    await dialog
      .getByRole("spinbutton", { name: "Budget limit" })
      .fill("500");

    // Select an allowed model: chip-selector if models loaded, else textbox
    const modelChip = dialog.getByText("gpt-4o", { exact: true });
    if (await modelChip.isVisible()) {
      await modelChip.click();
    } else {
      await dialog
        .getByRole("textbox", { name: /Allowed models/ })
        .fill("gpt-4o");
    }

    await dialog.getByRole("button", { name: "Create team" }).click();

    // Dialog closes (may take a moment for mutation) and team appears in table
    await expect(dialog).toBeHidden({ timeout: 10_000 });
    const table = page.getByRole("table");
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table.getByText(teamName)).toBeVisible();
  });

  test("search filters teams", async ({ page }) => {
    await page.goto("/ui/teams");

    // Wait for any existing teams to render
    await page.waitForTimeout(1000);

    await page
      .getByRole("textbox", { name: "Search teams" })
      .fill("nonexistent_team_xyz");

    // Should show either empty table or empty state
    await page.waitForTimeout(500);
  });
});
