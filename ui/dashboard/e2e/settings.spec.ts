import { test, expect } from "@playwright/test";

test.describe("Settings Page", () => {
  test("renders configuration section", async ({ page }) => {
    await page.goto("/ui/settings");

    await expect(
      page.getByRole("heading", { name: "Settings" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Configuration" }),
    ).toBeVisible();

    // Config values displayed
    await expect(page.getByText("config_hash")).toBeVisible();
    await expect(page.getByText("model_count")).toBeVisible();
    await expect(page.getByText("routing_strategy")).toBeVisible();
  });

  test("has edit and reload buttons", async ({ page }) => {
    await page.goto("/ui/settings");

    await expect(
      page.getByRole("button", { name: "Edit Settings" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Reload from file" }),
    ).toBeVisible();
  });

  test("edit mode shows form fields", async ({ page }) => {
    await page.goto("/ui/settings");

    await page.getByRole("button", { name: "Edit Settings" }).click();

    // General Settings section
    await expect(
      page.getByRole("heading", { name: "General Settings" }),
    ).toBeVisible();

    // Form fields
    await expect(page.getByText("Log Level")).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Request Timeout" }),
    ).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Max Request Size" }),
    ).toBeVisible();
    await expect(page.getByText("Block Robots")).toBeVisible();

    // CORS Allowed Origins editor
    await expect(page.getByText("CORS Allowed Origins")).toBeVisible();

    // Router Settings section
    await expect(
      page.getByRole("heading", { name: "Router Settings" }),
    ).toBeVisible();
    await expect(page.getByText("Routing Strategy")).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Num Retries" }),
    ).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Retry Delay" }),
    ).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: /Cooldown Time/ }),
    ).toBeVisible();
    await expect(page.getByText("Enable Health Check")).toBeVisible();

    // Model Fallbacks editor
    await expect(page.getByText("Model Fallbacks")).toBeVisible();

    // Cache Settings section
    await expect(
      page.getByRole("heading", { name: "Cache Settings" }),
    ).toBeVisible();
    await expect(page.getByText("Enable Response Caching")).toBeVisible();
    await expect(page.getByText("Cache Type")).toBeVisible();
    await expect(page.getByText("Cache TTL")).toBeVisible();

    // Save and Cancel buttons
    await expect(
      page.getByRole("button", { name: "Save Settings" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Cancel" }),
    ).toBeVisible();
  });

  test("cancel returns to read-only mode", async ({ page }) => {
    await page.goto("/ui/settings");

    await page.getByRole("button", { name: "Edit Settings" }).click();
    await expect(
      page.getByRole("button", { name: "Cancel" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    // Back to read-only
    await expect(
      page.getByRole("button", { name: "Edit Settings" }),
    ).toBeVisible();
  });

  test("save settings persists changes", async ({ page }) => {
    await page.goto("/ui/settings");

    // Enter edit mode
    await page.getByRole("button", { name: "Edit Settings" }).click();

    // Change num_retries
    const retriesInput = page.getByRole("spinbutton", {
      name: "Num Retries",
    });
    const currentValue = await retriesInput.inputValue();
    const newValue = currentValue === "5" ? "3" : "5";
    await retriesInput.fill(newValue);

    // Save
    await page.getByRole("button", { name: "Save Settings" }).click();

    // Success notification
    await expect(page.getByText("Settings saved")).toBeVisible();

    // Verify the value persisted
    await expect(page.getByText(`num_retries`)).toBeVisible();
    await expect(page.getByText(newValue, { exact: true })).toBeVisible();
  });

  test("shows SSO providers section", async ({ page }) => {
    await page.goto("/ui/settings");

    await expect(
      page.getByRole("heading", { name: "SSO Providers" }),
    ).toBeVisible();
  });

  test("displays expanded config fields in read-only mode", async ({ page }) => {
    await page.goto("/ui/settings");

    // New fields returned by expanded GET /config
    await expect(page.getByText("log_level")).toBeVisible();
    await expect(page.getByText("request_timeout")).toBeVisible();
    await expect(page.getByText("cors_allow_origins")).toBeVisible();
    await expect(page.getByText("cooldown_time")).toBeVisible();
    await expect(page.getByText("max_request_size_mb")).toBeVisible();
    await expect(page.getByText("max_response_size_mb")).toBeVisible();
  });

  test("CORS origins editor works", async ({ page }) => {
    await page.goto("/ui/settings");

    await page.getByRole("button", { name: "Edit Settings" }).click();

    // CORS origins section visible with existing origin
    await expect(page.getByText("CORS Allowed Origins")).toBeVisible();

    // The default "*" origin should be shown as a tag
    const corsSection = page.locator("text=CORS Allowed Origins").locator("..");
    await expect(corsSection).toBeVisible();
  });

  test("cache settings can be toggled", async ({ page }) => {
    await page.goto("/ui/settings");

    await page.getByRole("button", { name: "Edit Settings" }).click();

    // Cache settings section
    const cacheCheckbox = page.getByRole("checkbox", { name: "Enable Response Caching" });
    const cacheType = page.getByRole("combobox").last();
    const cacheTTL = page.getByRole("spinbutton", { name: "Cache TTL" });

    // Initially disabled controls (cache off by default)
    await expect(cacheType).toBeDisabled();
    await expect(cacheTTL).toBeDisabled();

    // Enable cache
    await cacheCheckbox.check();
    await expect(cacheType).toBeEnabled();
    await expect(cacheTTL).toBeEnabled();

    // Disable cache again
    await cacheCheckbox.uncheck();
    await expect(cacheType).toBeDisabled();
    await expect(cacheTTL).toBeDisabled();
  });
});
