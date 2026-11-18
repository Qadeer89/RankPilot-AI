import { expect, test, type Page, type Route } from "@playwright/test";
import { SITE } from "./support/fakeApi";

type Json = Record<string, unknown>;
const ORG = "00000000-0000-4000-8000-000000000001";
const PAGE_URL = `/dashboard/websites/${SITE}/growth`;
const BASELINE_MSG = "Your initial SEO baseline is ready. Connect Google Search Console and Analytics to measure actual search performance and organic traffic.";

const JOURNEY = {
  mode: "baseline", message: BASELINE_MSG, baseline: { taken_at: "2026-11-01T10:00:00Z", reconstructed: false }, last_analysis_at: "2026-11-01T10:00:00Z",
  integrations: { google_search_console: { connected: false, has_data: false }, ga4: { connected: false, has_data: false }, cms: null },
  panels: [
    { panel: "Website health and issues", available: true, source: "RankPilot crawl", reason: null },
    { panel: "Organic clicks, impressions, position", available: false, source: "Google Search Console", reason: "Requires Google Search Console." },
  ],
  next_actions: [{ key: "business_profile", text: "Confirm your business profile", detail: "It helps RankPilot suggest relevant search topics." }, { key: "connect_gsc", text: "Connect Google Search Console", detail: null }],
  recommendations: { total: 2, by_priority: { critical: 1, low: 1 }, by_type: {}, by_stage: {} }, expectations: "No result, ranking or traffic level is guaranteed.",
};
const PLAN = {
  generated_from: { pages: 3, open_issues: 2, critical_issues: 1, open_recommendations: 2 }, size_class: "small", pace_note: "With 3 page(s), much of this can finish sooner than 30 days.",
  disclaimer: "Completing it does not guarantee higher rankings.", generated_at: "2026-11-18T10:00:00Z",
  stages: [{ days: "1-3", title: "Discovery and baseline", items: [{ text: "Connect Google Search Console", status: "todo", basis: "Not connected, so there is no verified search performance.", count: null }] }],
};
const REC = (id: string, title: string, priority: string, type: string) => ({
  id, kind: "seo_opportunity", title, affected: "https://x.example/a", type, problem: "Problem text", evidence: {}, why_it_matters: "Why text", suggested_solution: "Do it", implementation: "Review it",
  priority, effort: "low", benefit_category: "x", validation: "A re-crawl confirms it.", stage: "recommended", actions: ["approve"], data_source: "RankPilot crawl",
});

class Fake {
  profile: Json = { exists: false, confirmed: false, business_type: null, industry: null, offerings: [], target_customers: [], objective: null, known_competitors: [], ai_suggestions: null, confirmed_at: null, target_countries: ["PK"] };
  calls: { path: string; method: string; body: string | null; query: URLSearchParams }[] = [];

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
    this.calls.push({ path: url.pathname, method: req.method(), body: req.postData(), query: url.searchParams });
    const p = url.pathname;
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    if (p.endsWith("/growth/journey")) return this.json(route, JOURNEY);
    if (p.endsWith("/growth/plan")) return this.json(route, PLAN);
    if (p.endsWith("/growth/recommendations")) {
      const all = [REC("a", "Add a title", "critical", "on_page"), REC("b", "Cover a topic", "low", "competitor_gap")];
      const pr = url.searchParams.get("priority");
      const items = pr ? all.filter((r) => r.priority === pr) : all;
      return this.json(route, { items, page: 1, page_size: 25, total: items.length, pages: 1, summary: JOURNEY.recommendations });
    }
    if (p.endsWith("/business-profile/suggest")) {
      this.profile = { ...this.profile, ai_suggestions: { business_type: "physiotherapy clinic", industry: "Healthcare", offerings: ["Back pain therapy"], audiences: ["Athletes"], objective_ideas: ["More appointments"],
        dropped_unsupported_offerings: ["Heart surgery"], label: "AI suggestions from your website's own text; nothing is saved until you confirm them." } };
      return this.json(route, this.profile);
    }
    if (p.endsWith("/business-profile")) {
      if (req.method() === "PUT") { this.profile = { ...this.profile, ...JSON.parse(req.postData() ?? "{}"), exists: true, confirmed: true, confirmed_at: "2026-11-18T10:00:00Z" }; return this.json(route, this.profile); }
      return this.json(route, this.profile);
    }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

async function open(page: Page, fake: Fake) {
  await fake.install(page);
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { name: "Growth Plan" })).toBeVisible();
  await expect(page.getByTestId("journey-message")).toBeVisible(); // the account and data have loaded
}

test("a new project sees the baseline message and 'not available' instead of invented numbers", async ({ page }) => {
  await open(page, new Fake());
  await expect(page.getByTestId("journey-message")).toHaveText(BASELINE_MSG);
  const panels = page.getByTestId("panels");
  await expect(panels.getByRole("row", { name: /Organic clicks/ })).toContainText("Not available — Requires Google Search Console.");
  await expect(panels.getByRole("row", { name: /Website health/ })).toContainText("Available");
  await expect(page.getByTestId("next-actions")).toContainText("Confirm your business profile");
});

test("the 30-day plan shows what each item is based on and does not promise results", async ({ page }) => {
  await open(page, new Fake());
  await expect(page.getByTestId("plan-pace")).toContainText("sooner than 30 days");
  await expect(page.getByText("Not connected, so there is no verified search performance.")).toBeVisible();
  await expect(page.getByTestId("plan-disclaimer")).toContainText("does not guarantee");
});

test("recommendations are one list and the priority filter is applied by the server", async ({ page }) => {
  const fake = new Fake();
  await open(page, fake);
  await expect(page.getByTestId("rec")).toHaveCount(2);
  await page.getByLabel("Priority").selectOption("critical");
  await expect(page.getByTestId("rec")).toHaveCount(1);
  await expect(page.getByTestId("rec").first()).toContainText("Add a title");
  expect(fake.calls.some((c) => c.path.endsWith("/growth/recommendations") && c.query.get("priority") === "critical")).toBe(true);
});

test("AI suggestions are labelled, unsupported ones are explained, and nothing is saved until the person confirms", async ({ page }) => {
  const fake = new Fake();
  await open(page, fake);
  await page.getByRole("button", { name: "Suggest from my website" }).click();
  const box = page.getByTestId("ai-suggestions");
  await expect(box).toContainText("not saved until you confirm");
  await expect(box).toContainText("Left out because your site does not mention them: Heart surgery");
  expect(fake.calls.some((c) => c.method === "PUT")).toBe(false);
  await box.getByRole("button", { name: "Copy into the form" }).click();
  await expect(page.getByLabel("Business type")).toHaveValue("physiotherapy clinic");
  expect(fake.calls.some((c) => c.method === "PUT")).toBe(false);
  await page.getByLabel("Business type").fill("sports physiotherapy clinic");
  await page.getByRole("button", { name: "Confirm business profile" }).click();
  await expect(page.getByText("Business profile confirmed.", { exact: true })).toBeVisible();
  const put = fake.calls.find((c) => c.method === "PUT")!;
  expect(JSON.parse(put.body!)).toMatchObject({ business_type: "sports physiotherapy clinic", offerings: ["Back pain therapy"], target_customers: ["Athletes"] });
});
