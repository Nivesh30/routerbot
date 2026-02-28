import { test, expect } from "@playwright/test";

test.describe("Keys Page", () => {
  test("renders keys page with generate button", async ({ page }) => {
    await page.goto("/ui/keys");

    await expect(
      page.getByRole("heading", { name: "Virtual Keys" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Generate Key" }),
    ).toBeVisible();
  });

  test("generate key modal opens and validates", async ({ page }) => {
    await page.goto("/ui/keys");

    await page.getByRole("button", { name: "Generate Key" }).click();

    // Modal appears
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Generate Virtual Key" }),
    ).toBeVisible();

    // Form fields present — User ID and Team ID are dropdowns
    await expect(dialog.getByRole("combobox").first()).toBeVisible();
    await expect(dialog.getByText("User ID")).toBeVisible();
    await expect(dialog.getByText("Team ID")).toBeVisible();
    await expect(dialog.getByText("Allowed Models")).toBeVisible();
    await expect(
      dialog.getByRole("spinbutton", { name: "Budget Limit" }),
    ).toBeVisible();

    // Cancel closes modal
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("can generate a key and see it in table", async ({ page }) => {
    await page.goto("/ui/keys");

    await page.getByRole("button", { name: "Generate Key" }).click();
    const dialog = page.getByRole("dialog");

    // Fill optional fields — models are chip-selectors when models are loaded
    // Click the gpt-4o-mini chip to select it
    const modelChip = dialog.getByText("gpt-4o-mini", { exact: true });
    if (await modelChip.isVisible()) {
      await modelChip.click();
    } else {
      // Fallback: text input when no models loaded
      await dialog
        .getByRole("textbox", { name: /gpt-4o.*comma-separated/ })
        .fill("gpt-4o-mini");
    }
    await dialog.getByRole("spinbutton", { name: "Budget Limit" }).fill("50");

    // Submit
    await dialog
      .getByRole("button", { name: "Generate", exact: true })
      .click();

    // Key reveal dialog
    await expect(
      page.getByRole("heading", { name: "Your New API Key" }),
    ).toBeVisible();
    await expect(page.getByText("you will not be able to see it again")).toBeVisible();

    // Dismiss
    await page.getByRole("button", { name: "Done" }).click();

    // Key appears in table
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByText("gpt-4o-mini").first()).toBeVisible();
  });
});
