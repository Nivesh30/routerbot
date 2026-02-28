import { test as setup, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const authFile = path.join(__dirname, ".auth", "user.json");

/**
 * Authenticate once and persist the storage state for all tests.
 */
setup("authenticate", async ({ page }) => {
  // Navigate to login
  await page.goto("/ui/login");

  // Fill master key and submit
  await page.getByPlaceholder("Master key or API key").fill("test");
  await page.getByRole("button", { name: "Sign In" }).click();

  // Wait for redirect to dashboard
  await page.waitForURL("**/ui", { timeout: 10_000 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  // Save signed-in state
  await page.context().storageState({ path: authFile });
});
