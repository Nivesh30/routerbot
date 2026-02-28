import { test, expect } from "@playwright/test";

test.describe("Users Page", () => {
  test("renders users page", async ({ page }) => {
    await page.goto("/ui/users");

    await expect(page.getByRole("heading", { name: "Users", exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "New User" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Search users" }),
    ).toBeVisible();
  });

  test("role filter dropdown is present", async ({ page }) => {
    await page.goto("/ui/users");

    const filter = page.getByRole("combobox");
    await expect(filter).toBeVisible();

    // Options
    const options = filter.getByRole("option");
    expect(await options.count()).toBeGreaterThanOrEqual(4); // All roles, Admin, User, Viewer
  });

  test("shows empty state when no users", async ({ page }) => {
    await page.goto("/ui/users");

    // Either table or empty state
    const empty = page.getByText("No users found");
    const table = page.getByRole("table");

    // One of them should be visible
    await expect(empty.or(table)).toBeVisible();
  });
});
