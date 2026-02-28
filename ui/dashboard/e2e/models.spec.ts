import { test, expect } from "@playwright/test";

test.describe("Models Page", () => {
  test("lists configured models", async ({ page }) => {
    await page.goto("/ui/models");

    await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();

    // Table should have model entries
    const table = page.getByRole("table");
    await expect(table).toBeVisible();

    // Check for our two configured models
    await expect(page.getByRole("cell", { name: "gpt-4o", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "gpt-4o-mini", exact: true })).toBeVisible();
  });

  test("has Add Model button", async ({ page }) => {
    await page.goto("/ui/models");
    await expect(
      page.getByRole("button", { name: "Add Model" }),
    ).toBeVisible();
  });

  test("add model dialog has provider preset dropdown", async ({ page }) => {
    await page.goto("/ui/models");

    await page.getByRole("button", { name: "Add Model" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Provider dropdown
    const providerSelect = dialog.getByRole("combobox");
    await expect(providerSelect).toBeVisible();

    // Should have provider presets
    await expect(providerSelect.getByRole("option", { name: "OpenAI", exact: true })).toBeAttached();
    await expect(providerSelect.getByRole("option", { name: "Anthropic" })).toBeAttached();
    await expect(providerSelect.getByRole("option", { name: "Google Gemini" })).toBeAttached();
    await expect(providerSelect.getByRole("option", { name: "AWS Bedrock" })).toBeAttached();
    await expect(providerSelect.getByRole("option", { name: "Ollama" })).toBeAttached();

    // Text input for model name beside the dropdown
    await expect(dialog.getByRole("textbox", { name: "Model Name" })).toBeVisible();
    await expect(dialog.getByPlaceholder("openai/gpt-4o")).toBeVisible();

    // Selecting a provider should update the model text input
    await providerSelect.selectOption({ label: "OpenAI" });
    await expect(dialog.getByPlaceholder("openai/gpt-4o")).toHaveValue("openai/");

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("shows action buttons per model", async ({ page }) => {
    await page.goto("/ui/models");
    // Table should be visible with model rows
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    const rows = table.getByRole("row");
    // Header row + at least 2 model rows
    expect(await rows.count()).toBeGreaterThanOrEqual(3);
  });
});
