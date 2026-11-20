import { expect, test, type Page, type Route } from "@playwright/test";
import { SITE } from "./support/fakeApi";

type Json = Record<string, unknown>;
const ORG = "00000000-0000-4000-8000-000000000001";
const PAGE_URL = `/dashboard/websites/${SITE}/history`;

const BASELINE = { id: "s-base", taken_at: "2026-10-04T10:00:00Z", type: "crawl", is_baseline: true, status: "completed", reconstructed: false, analysis_version: "rules-2026.11", scoring_version: "health-v1", partial_reason: null, health_overall: 62, open_issues: 65, pages_crawled: 40 };
const LATEST = { ...BASELINE, id: "s-latest", taken_at: "2026-11-16T10:00:00Z", is_baseline: false, health_overall: 91, open_issues: 28, pages_crawled: 143 };

function overview(over: Json = {}): Json {
  return {
    baseline: BASELINE, latest: LATEST,
    health: { initial: 62, current: 91, previous: 62, change: 29, change_pct: 46.77, status: "improved", note: "RankPilot's own measure of website health. It is not a Google ranking." },
    issues: { identified_total: 80, resolved: 52, still_open: 28, new_since_baseline: 15, note: "n" },
    work: { pages_optimized: 12, recommendations_implemented: 9, recommendations_validated: 6, recommendations_failed: 1 },
    data_sources: { crawler: { available: true, reason: null }, google_search_console: { available: false, reason: "Search Console is not connected. Google performance tracking starts when it is connected." }, ga4: { available: false, reason: "Google Analytics is not connected." } },
    baseline_performance: { available: false }, ...over,
  };
}

const COMPARE = {
  from: BASELINE, to: LATEST, comparison_period: { start: "2026-10-04", end: "2026-11-16" }, warnings: [],
  rows: [
    { group: "Health", label: "Overall SEO health score", source: "RankPilot crawl", previous: 62, current: 91, change: 29, change_pct: 46.77, status: "improved" },
    { group: "Issues", label: "Open issues", source: "RankPilot crawl", previous: 65, current: 28, change: -37, change_pct: -56.92, status: "improved" },
    { group: "Health", label: "Content score", source: "RankPilot crawl", previous: null, current: null, change: null, change_pct: null, status: "not_available" },
  ],
  issue_changes: { available: true, resolved: 52, new: 15, still_open: 13 },
};

class FakeHistory {
  calls: { path: string; query: URLSearchParams }[] = [];
  ov: Json = overview();
  search: Json = { available: false, reason: "Search Console is not connected, so there is no Google performance to compare.", rows: [], freshness: { latest_data_date: null, last_synced_at: null, note: "" } };
  compareStatus = 200;
  events: Json[] = [{ id: "e1", category: "snapshot", event_type: "baseline_established", title: "Baseline established: where this project started", occurred_at: "2026-10-04T10:00:00Z", detail: {} }];

  requests(part: string) { return this.calls.filter((c) => c.path.includes(part)); }

  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" }, body: JSON.stringify(body) });
  }

  private async handle(route: Route) {
    const req = route.request();
    if (req.method() === "OPTIONS") return this.json(route, {}, 204);
    const url = new URL(req.url());
    this.calls.push({ path: url.pathname, query: url.searchParams });
    const p = url.pathname;
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    if (p.endsWith("/history/overview")) return this.json(route, this.ov);
    if (p.endsWith("/history/snapshots")) return this.json(route, { items: [LATEST, BASELINE], total: 2 });
    if (p.endsWith("/history/compare")) {
      if (this.compareStatus !== 200) return this.json(route, { detail: { code: "snapshot_not_found", message: "No snapshot found for 'x'." } }, this.compareStatus);
      return this.json(route, COMPARE);
    }
    if (p.endsWith("/history/search-comparison")) return this.json(route, this.search);
    if (p.endsWith("/history/series")) {
      const metric = url.searchParams.get("metric");
      const google = ["clicks", "impressions", "ctr", "position"].includes(metric ?? "");
      return this.json(route, google
        ? { metric, label: "Clicks", family: "google_search", source: "Google Search Console", start: "2026-08-01", end: "2026-11-16", available: false, points: [], note: "Data reported by Google; days Google has no data for are left out, not shown as zero." }
        : { metric, label: "RankPilot health score", family: "internal_score", source: "RankPilot crawl", start: "2026-08-01", end: "2026-11-16", available: true, points: [{ date: "2026-10-04", value: 62 }, { date: "2026-11-16", value: 91 }], note: "RankPilot's own measure; it does not show how Google ranks the site." });
    }
    if (p.endsWith("/history/timeline")) {
      const cat = url.searchParams.get("category");
      const items = cat ? this.events.filter((e) => e.category === cat) : this.events;
      return this.json(route, { items, page: 1, page_size: 20, total: items.length, pages: 1 });
    }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

async function open(page: Page, fake: FakeHistory) {
  await fake.install(page);
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { name: /History & Progress/ })).toBeVisible();
}

test("progress since the baseline shows real numbers and where they come from", async ({ page }) => {
  const fake = new FakeHistory();
  await open(page, fake);
  const card = page.getByRole("region", { name: "Overall progress" });
  await expect(card.getByText("Initial health score")).toBeVisible();
  await expect(card).toContainText("62");
  await expect(card).toContainText("91");
  await expect(card).toContainText("+29 (+46.77%)");
  await expect(card).toContainText("not a Google ranking");
  await expect(card.getByText("Issues resolved")).toBeVisible();
  await expect(card.getByTestId("data-sources")).toContainText("Google Search Console: Search Console is not connected");
});

test("before and after shows previous, current, change, status and source, and says when something is not available", async ({ page }) => {
  const fake = new FakeHistory();
  await open(page, fake);
  const table = page.getByTestId("compare-table");
  const health = table.getByRole("row", { name: /Overall SEO health score/ });
  await expect(health).toContainText("62");
  await expect(health).toContainText("91");
  await expect(health).toContainText("Improved");
  await expect(health).toContainText("RankPilot crawl");
  const open_ = table.getByRole("row", { name: /Open issues/ });
  await expect(open_).toContainText("-37 (-56.92%)");
  await expect(open_).toContainText("Improved"); // fewer issues is an improvement
  await expect(table.getByRole("row", { name: /Content score/ })).toContainText("Not available");
  await expect(page.getByTestId("issue-changes")).toContainText("Resolved 52 · New 15 · Still open 13");
});

test("changing the snapshots asks the server for exactly those two", async ({ page }) => {
  const fake = new FakeHistory();
  await open(page, fake);
  await page.getByLabel("Later snapshot").selectOption("previous");
  await page.getByLabel("Earlier snapshot").selectOption("s-latest");
  await expect.poll(() => fake.requests("/history/compare").some((c) => c.query.get("from") === "s-latest" && c.query.get("to") === "previous")).toBe(true);
});

test("without Search Console the page explains why instead of showing zeros", async ({ page }) => {
  const fake = new FakeHistory();
  await open(page, fake);
  await expect(page.getByTestId("search-unavailable")).toContainText("Search Console is not connected");
  await expect(page.getByTestId("search-table")).toHaveCount(0);
  await page.getByLabel("Measure").selectOption("clicks");
  await expect(page.getByTestId("chart-empty")).toContainText("No data has been stored");
  await expect(page.getByText("left out, not shown as zero")).toBeVisible();
});

test("a search comparison shows both periods, the data date and warns about incomplete data", async ({ page }) => {
  const fake = new FakeHistory();
  fake.search = {
    available: true, against: "previous",
    previous: { start: "2026-09-16", end: "2026-10-13", days: 28, days_with_data: 5, coverage: 0.18, available: true },
    current: { start: "2026-10-14", end: "2026-11-10", days: 28, days_with_data: 28, coverage: 1, available: true },
    rows: [
      { label: "Clicks", source: "Google Search Console", previous: 280, current: 420, change: 140, change_pct: 50, status: "improved" },
      { label: "CTR", source: "Google Search Console", previous: 0.05, current: 0.06, change: 0.01, change_pct: 20, status: "improved" },
      { label: "Average position", source: "Google Search Console", previous: 9, current: 6, change: -3, change_pct: -33.33, status: "improved" },
    ],
    warnings: ["The earlier period has data for only 5 of 28 days, so its totals are incomplete."],
    freshness: { latest_data_date: "2026-11-10", last_synced_at: "2026-11-13T01:00:00Z", note: "Search Console reports with a delay of a few days, so the newest days are not yet available." },
    note: "A difference between two periods does not show that any single change caused it.",
  };
  await open(page, fake);
  const table = page.getByTestId("search-table");
  await expect(table.getByRole("row", { name: /Clicks/ })).toContainText("420");
  await expect(table.getByRole("row", { name: /CTR/ })).toContainText("6.00%");
  await expect(table.getByRole("row", { name: /Average position/ })).toContainText("Improved");
  await expect(page.getByTestId("search-warning")).toContainText("only 5 of 28 days");
  await expect(page.getByText("Latest data date: 2026-11-10")).toBeVisible();
  await expect(page.getByText("does not show that any single change caused it")).toBeVisible();
  await page.getByLabel("Compare with").selectOption("baseline");
  await page.getByLabel("Period").selectOption("custom");
  await page.locator('input[type="date"]').first().fill("2026-10-01");
  await page.locator('input[type="date"]').nth(1).fill("2026-10-31");
  await expect.poll(() => fake.requests("/history/search-comparison").some((c) => c.query.get("against") === "baseline" && c.query.get("period") === "custom" && c.query.get("start") === "2026-10-01" && c.query.get("end") === "2026-10-31")).toBe(true);
});

test("the trend chart is drawn from the stored points and labelled as RankPilot's own measure", async ({ page }) => {
  const fake = new FakeHistory();
  await open(page, fake);
  await expect(page.getByTestId("chart")).toBeVisible();
  await expect(page.getByText("it does not show how Google ranks the site")).toBeVisible();
  await page.getByLabel("Range").selectOption("365");
  await expect.poll(() => fake.requests("/history/series").some((c) => c.query.get("metric") === "health_overall")).toBe(true);
});

test("the timeline lists real events and filters by category", async ({ page }) => {
  const fake = new FakeHistory();
  fake.events.push({ id: "e2", category: "integration", event_type: "gsc_connected", title: "Google Search Console connected", occurred_at: "2026-11-01T09:00:00Z", detail: {} });
  await open(page, fake);
  await expect(page.getByTestId("timeline")).toContainText("Baseline established");
  await page.getByLabel("Category").selectOption("integration");
  await expect(page.getByTestId("timeline")).toContainText("Google Search Console connected");
  await expect(page.getByTestId("timeline")).not.toContainText("Baseline established");
  await page.getByLabel("Category").selectOption("project");
  await expect(page.getByTestId("timeline-empty")).toBeVisible();
});

test("a project with no analysis yet has no baseline and says so", async ({ page }) => {
  const fake = new FakeHistory();
  fake.ov = overview({ baseline: null, latest: null, health: { initial: null, current: null, previous: null, change: null, change_pct: null, status: "not_available", note: "n" },
    data_sources: { crawler: { available: false, reason: "No analysis has completed yet." }, google_search_console: { available: false, reason: "Search Console is not connected." }, ga4: { available: false, reason: "Google Analytics is not connected." } } });
  await open(page, fake);
  await expect(page.getByTestId("no-baseline")).toContainText("saved automatically when the first crawl finishes");
  await expect(page.getByRole("region", { name: "Before and after" })).toHaveCount(0);
});

test("a failed comparison shows the reason", async ({ page }) => {
  const fake = new FakeHistory();
  fake.compareStatus = 404;
  await open(page, fake);
  await expect(page.getByTestId("compare-error")).toContainText("No snapshot found");
});

test("a rebuilt baseline is labelled as such", async ({ page }) => {
  const fake = new FakeHistory();
  fake.ov = overview({ baseline: { ...BASELINE, reconstructed: true } });
  await open(page, fake);
  await expect(page.getByText("rebuilt from the health score stored at the time")).toBeVisible();
});

test("an overall score that averages different components is shown as not comparable, with the like-for-like figure", async ({ page }) => {
  const fake = new FakeHistory();
  fake.ov = overview({
    health: { initial: 96.66, current: 90.85, previous: 96.66, change: null, change_pct: null, status: "not_comparable", like_for_like: { components: ["technical", "on_page", "content"], previous: 96.66, current: 95.9 },
              note: "RankPilot's own measure of website health. It is not a Google ranking. The two overall scores average different components, so they are not directly comparable." },
    work: { pages_optimized: 30, changes_applied: 106, changes_validated: 105, changes_failed: 1, recommendations_implemented: 40, recommendations_validated: 39, recommendations_failed: 1 },
  });
  await open(page, fake);
  const card = page.getByRole("region", { name: "Overall progress" });
  await expect(card).toContainText("Not comparable");
  await expect(card).not.toContainText("Declined");
  await expect(page.getByTestId("like-for-like")).toContainText("96.66 → 95.9");
  await expect(card).toContainText("Changes applied");
  await expect(card).toContainText("106");
});

test("small Search Console volumes get no better/worse verdict, and CTR is shown in percentage points", async ({ page }) => {
  const fake = new FakeHistory();
  fake.search = {
    available: true, against: "previous", freshness: { latest_data_date: "2026-11-17", last_synced_at: "2026-11-20T10:00:00Z", note: "Search Console reports with a delay of a few days, so the newest days are not yet available." },
    previous: { start: "2026-09-23", end: "2026-10-20" }, current: { start: "2026-10-21", end: "2026-11-17" },
    rows: [
      { label: "Clicks", source: "Google Search Console", previous: 16, current: 14, change: -2, change_pct: -12.5, status: "low_volume" },
      { label: "CTR", source: "Google Search Console", previous: 0.0442, current: 0.0317, change: -0.0125, change_pct: -28.28, status: "low_volume" },
      { label: "Average position", source: "Google Search Console", previous: 4.2, current: 5.4, change: 1.189, change_pct: 28.44, status: "low_volume" },
    ],
    warnings: ["Small numbers: 16 and 14 clicks, 362 and 442 impressions. Changes this small are often random, so they are shown without a better/worse verdict."], note: "n",
  };
  await open(page, fake);
  await expect(page.getByTestId("search-warning")).toContainText("Small numbers");
  const table = page.locator("table").filter({ hasText: "Average position" }).first();
  await expect(table.getByRole("row", { name: /^Clicks/ })).toContainText("Too few to judge");
  await expect(table.getByRole("row", { name: /^CTR/ })).toContainText("-1.25 percentage points");
  await expect(table.getByRole("row", { name: /^Average position/ })).toContainText("lower in results");
  await expect(table).not.toContainText("Declined");
});
