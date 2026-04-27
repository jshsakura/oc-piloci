import { test, expect } from "@playwright/test";

test.describe("Login Page", () => {
  test("should show login form", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "로그인" })).toBeVisible();
    await expect(page.getByLabel("이메일")).toBeVisible();
    await expect(page.getByLabel("비밀번호")).toBeVisible();
  });

  test("should show error on invalid login", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("이메일").fill("wrong@example.com");
    await page.getByLabel("비밀번호").fill("wrongpassword");
    await page.getByRole("button", { name: "로그인" }).click();

    // The error message depends on the API response, but we expect some error to appear
    await expect(page.locator("text=이메일 또는 비밀번호가 올바르지 않습니다")).toBeVisible();
  });
});
