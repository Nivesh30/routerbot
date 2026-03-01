import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E tests for the RouterBot Dashboard.
 *
 * Assumes the app is running at http://localhost:8000
 * (docker compose up or local dev server).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // sequential — we reuse login state
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    // Setup project: authenticate and save storage state
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "./e2e/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],
});
