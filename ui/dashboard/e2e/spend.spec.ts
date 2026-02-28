import { test, expect } from "@playwright/test";

test.describe("Spend Page", () => {
  test("renders spend analytics with KPIs", async ({ page }) => {
    await page.goto("/ui/spend");

    await expect(
      page.getByRole("heading", { name: "Spend Analytics" }),
    ).toBeVisible();

    // KPI cards
    await expect(page.getByText("Total Spend")).toBeVisible();
    await expect(page.getByText("Total Requests")).toBeVisible();
    await expect(page.getByText("Total Tokens")).toBeVisible();
  });

  test("has period selector", async ({ page }) => {
    await page.goto("/ui/spend");

    const select = page.getByRole("combobox");
    await expect(select).toBeVisible();

    // Select options exist (they're hidden until dropdown opens, so just check count)
    const options = select.locator("option");
    expect(await options.count()).toBeGreaterThanOrEqual(3);
  });

  test("has overview and logs tabs", async ({ page }) => {
    await page.goto("/ui/spend");

    await expect(page.getByRole("button", { name: "overview" })).toBeVisible();
    await expect(page.getByRole("button", { name: "logs" })).toBeVisible();
  });

  test("breakdown chart has group-by options", async ({ page }) => {
    await page.goto("/ui/spend");

    await expect(
      page.getByRole("heading", { name: "Spend Breakdown" }),
    ).toBeVisible();

    for (const group of ["model", "provider", "team", "user"]) {
      await expect(
        page.getByRole("button", { name: group }),
      ).toBeVisible();
    }
  });

  test("export CSV button is present", async ({ page }) => {
    await page.goto("/ui/spend");

    await expect(
      page.getByRole("button", { name: "Export CSV" }),
    ).toBeVisible();
  });

  test("logs tab shows spend records or empty state", async ({ page }) => {
    await page.goto("/ui/spend");

    await page.getByRole("button", { name: "logs" }).click();

    // Either table or empty state for spend records
    const empty = page.getByText("No spend records");
    const table = page.getByRole("table");
    await expect(empty.or(table)).toBeVisible();
  });
});
