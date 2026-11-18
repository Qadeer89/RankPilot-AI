import { expect, test } from "@playwright/test";

const doc = (id: string, title: string, source_type: string) => ({ id, title, category: "general", source_type, version: 1, is_active: true, content: "x", source_key: id, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z" });

test("admin sees what the page is for, customer help articles first, and internal docs are labelled and not editable", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
  await page.route("**/api/v1/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const h = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: h });
    const json = p.endsWith("/me") ? { user: { id: "u1", email: "o@example.com", is_platform_admin: true, is_super_admin: false, email_verified: true }, organizations: [] }
      : p.endsWith("/admin/knowledge/documents") ? [doc("1", "RankPilot AI --- API Specification", "seed_docs"), doc("2", "How do I connect Search Console?", "admin_authored")]
      : p.endsWith("/ingestion-jobs") ? [] : [];
    return route.fulfill({ status: 200, contentType: "application/json", headers: h, body: JSON.stringify(json) });
  });
  await page.goto("/dashboard/admin/knowledge");
  await expect(page.getByTestId("kb-explain")).toContainText("answers customers' questions");
  await expect(page.getByText("How do I connect Search Console?")).toBeVisible();
  await expect(page.getByText("API Specification")).toHaveCount(0); // internal docs are behind their own filter
  await page.getByRole("button", { name: /Internal technical docs/ }).click();
  const internal = page.getByText("API Specification");
  await expect(internal).toBeVisible();
  await expect(page.getByText("Internal technical doc ·")).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  await page.getByRole("button", { name: /Customer help articles/ }).click();
  await page.getByRole("button", { name: "+ New document" }).click();
  await page.getByRole("button", { name: "Use help-article template" }).click();
  await expect(page.getByLabel("Content")).toHaveValue(/Short answer:/);
});
