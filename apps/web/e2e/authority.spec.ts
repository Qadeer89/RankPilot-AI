import { expect, test, type Page, type Route } from "@playwright/test";
import { SITE } from "./support/fakeApi";

const ORG = "00000000-0000-4000-8000-000000000001";
const URL_ = `/dashboard/websites/${SITE}/authority`;
const DISCLAIMER = "RankPilot's Domain Quality is calculated from your own crawl and search data. It is not Domain Rating, Domain Authority, Authority Score, Trust Flow or Citation Flow.";

const SIGNALS = [
  { key: "crawl_health", label: "Crawl Health", value: 92.5, weight: 0.15, status: "calculated", how: "60% pages answering 2xx + 40% pages without broken links.", inputs: {}, note: null },
  { key: "organic_visibility", label: "Organic Visibility", value: null, weight: 0.1, status: "not_available", how: "Share of pages with impressions.", inputs: {}, note: "Needs Search Console data." },
];
const analysis = (live: number) => ({ label: "Verified from the source pages you listed. This is not a count of every link to your site; RankPilot has no web-wide link index.", recorded: 1, verified_live: live, by_status: {}, unchecked: live ? 0 : 1,
  referring_domains: live, followed: live, nofollow_or_ugc_sponsored: 0, top_domains: [], anchor_distribution: live ? [{ anchor: "example", links: 1, share: 1 }] : [], destination_pages: [], single_domain_share: null, lost: [] });

class Fake {
  assessed = false; checked = false; added = false; calls: { path: string; method: string; body: string | null }[] = [];
  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/api/v1/**", (r) => this.handle(r));
  }
  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" }, body: JSON.stringify(body) });
  }
  private async handle(route: Route) {
    const req = route.request();
    if (req.method() === "OPTIONS") return this.json(route, {}, 204);
    const p = new URL(req.url()).pathname;
    this.calls.push({ path: p, method: req.method(), body: req.postData() });
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    if (p.endsWith("/authority/refresh")) { this.assessed = true; return this.json(route, {}); }
    if (p.endsWith("/authority")) return this.json(route, { disclaimer: DISCLAIMER, empty_reason: "No assessment yet. Run one to calculate it from your latest crawl.", comparison: null, history: [],
      latest: this.assessed ? { id: "a", computed_at: "2026-11-23T10:00:00Z", formula_version: "authority-v1", domain_quality: 81.2, coverage: 0.9, confidence: "high", signals: SIGNALS, inputs: {}, data_source: "RankPilot calculated" } : null });
    if (p.endsWith("/backlinks/import")) { this.added = true; return this.json(route, { added: 1, duplicates: 0, rejected: [], truncated: 0 }); }
    if (p.endsWith("/backlinks/check")) { this.checked = true; return this.json(route, { checked: 1, remaining_in_batch: 0, analysis: analysis(1) }); }
    if (p.endsWith("/backlinks")) {
      const items = this.added ? [{ id: "b1", source_url: "https://blog.test/post", source_domain: "blog.test", target_url: this.checked ? "https://x.example/" : null, anchor_text: this.checked ? "example" : null, rel_values: [], is_nofollow: this.checked ? false : null,
        link_location: this.checked ? "content" : null, discovery_source: "user_provided", status: this.checked ? "live" : "unchecked", http_status: null, first_discovered_at: "2026-11-23T10:00:00Z", last_checked_at: this.checked ? "2026-11-23T10:05:00Z" : null,
        last_live_at: null, lost_at: null, note: null, data_source: this.checked ? "Verified from the source page" : "Not checked" }] : [];
      return this.json(route, { items, analysis: this.checked ? analysis(1) : { ...analysis(0), recorded: items.length }, limits: { max_import: 500, max_checks_per_call: 25 }, empty_reason: "No backlinks recorded yet. Add the pages that link to your site; RankPilot will verify each one." });
    }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

test("empty state, calculate, add and verify backlinks, with honest labels throughout", async ({ page }) => {
  const fake = new Fake();
  await fake.install(page);
  await page.goto(URL_);
  await expect(page.getByRole("heading", { name: "Authority & Backlinks" })).toBeVisible();
  await expect(page.getByTestId("authority-disclaimer")).toContainText("not Domain Rating");
  await expect(page.getByTestId("authority-empty")).toContainText("No assessment yet");
  await expect(page.getByTestId("backlinks-empty")).toContainText("No backlinks recorded yet");
  await expect(page.getByTestId("backlink-label")).toContainText("not a count of every link");

  await page.getByRole("button", { name: "Recalculate now" }).click();
  await expect(page.getByTestId("dq-score")).toHaveText("81.2");
  await expect(page.getByTestId("signals").getByRole("row", { name: /Organic Visibility/ })).toContainText("Not available");

  await page.getByLabel(/Pages that link to your site/).fill("https://blog.test/post");
  await page.getByRole("button", { name: "Add pages" }).click();
  await expect(page.getByTestId("backlink-row")).toContainText("Not checked");
  expect(JSON.parse(fake.calls.find((c) => c.path.endsWith("/backlinks/import"))!.body!)).toMatchObject({ source: "user_provided" });

  await page.getByRole("button", { name: /Verify links/ }).click();
  await expect(page.getByTestId("backlink-row")).toContainText("Live");
  await expect(page.getByTestId("backlink-row")).toContainText("Verified from the source page");
  await expect(page.getByTestId("live-count")).toHaveText("1");
});
