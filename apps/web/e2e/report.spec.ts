import { expect, test } from "@playwright/test";
import { SITE } from "./support/fakeApi";

const ORG = "00000000-0000-4000-8000-000000000001";
const LIMITS = ["The health score is RankPilot's own measure of technical and on-page quality. It is not a Google ranking and does not predict one."];

function report(over: Record<string, unknown> = {}) {
  return {
    project: { name: "Demo", url: "https://demo.example/" }, generated_at: "2026-11-18T10:00:00Z", has_progress: true, baseline: { taken_at: "2026-10-01T10:00:00Z" }, latest: { taken_at: "2026-11-18T10:00:00Z" },
    period: { start: "2026-10-01", end: "2026-11-18" }, health: { initial: 60, current: 88, note: "RankPilot's own measure." }, issues: { identified_total: 10, resolved: 6, still_open: 4, new_since_baseline: 1 },
    work: { pages_optimized: 3, recommendations_implemented: 2, recommendations_validated: 1, recommendations_failed: 0 },
    highlights: ["Overall SEO health score: 60 → 88, +28 (+46.67%) [RankPilot crawl]"], google: { available: false, reason: "Search Console is not connected, so there is no Google performance to compare.", lines: [] },
    data_sources: { crawler: { available: true, reason: null }, google_search_console: { available: false, reason: "Search Console is not connected." } }, warnings: [], limitations: LIMITS, ...over,
  };
}

async function open(page: import("@playwright/test").Page, body: unknown) {
  await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
  await page.route("**/api/v1/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const h = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: h });
    const json = p.endsWith("/me") ? { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] } : p.endsWith("/history/report") ? body : { detail: "x" };
    return route.fulfill({ status: 200, contentType: "application/json", headers: h, body: JSON.stringify(json) });
  });
  await page.goto(`/dashboard/websites/${SITE}/report`);
}

test("the report shows sourced changes, marks missing Google data 'Not available', and states its limits", async ({ page }) => {
  await open(page, report());
  const r = page.getByTestId("report");
  await expect(r).toContainText("60 → 88");
  await expect(r).toContainText("[RankPilot crawl]");
  await expect(page.getByTestId("google-na")).toContainText("Not available — Search Console is not connected");
  await expect(page.getByTestId("limitations")).toContainText("not a Google ranking");
});

test("a brand-new project's report says progress comes later instead of inventing any", async ({ page }) => {
  await open(page, report({ has_progress: false, highlights: [], period: null }));
  await expect(page.getByTestId("no-progress")).toContainText("Your starting point is saved");
});
