import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, ORG, SITE } from "./support/fakeApi";

type Json = Record<string, unknown>;
const PAGE_URL = `/dashboard/websites/${SITE}/keywords`;
const QUERY = "how long does inpatient rehab take";

function opportunity(over: Json = {}): Json {
  return {
    query: QUERY, categories: ["question", "long_tail", "conversational"], category_signals: ["starts with a question word"], word_count: 6,
    country: "PK", countries: { PK: 100 }, impressions: 100, clicks: 0, ctr: 0, average_position: 8, score: 82, tier: "high_opportunity",
    factors: [{ factor: "Demand", points: 20, max: 30, note: "100 impressions in the period" }, { factor: "CTR vs this site", points: 15, max: 15, note: "CTR 0.0% vs this site's median 10.0%" }],
    needs_review: false, title_heading_coverage: 0.5, trend: "stable", landing_page: { page_id: "p1", url: "https://clinic.example/inpatient" },
    other_pages: [], finding_id: null, status: "new", ...over,
  };
}

function finding(over: Json = {}): Json {
  return {
    id: "f1", query: QUERY, status: "ready_for_review", tier: "high_opportunity", score: 82, needs_review: false,
    target_page: { page_id: "p1", url: "https://clinic.example/inpatient" },
    answer_analysis: { level: "partial", reason: "The query's terms appear in the text but no section is dedicated to answering it.", missing_terms: ["long"] },
    ai_search_readiness: { label: "moderate", passed: 6, total: 10, ai_visibility: "unmeasured", disclaimer: "This checks content quality and structure. It does not measure or guarantee visibility in AI answers.",
      checks: [{ check: "Direct answer under a matching heading", status: "warn", evidence: "partial", advice: "Add a short section." }] },
    ai_status: "ok", ai_error: null,
    draft: { search_intent: "informational", user_question: "How long is inpatient rehab?", page_matches_intent: true, intent_note: "", current_answer_assessment: "None",
      missing_information: ["typical duration"], needs_owner_input: [], direct_answer: "Most inpatient programmes run for 28 to 90 days, and a clinician reviews the plan every week.",
      suggested_heading: "How long does inpatient rehab take?", faq_recommended: false, faq_suggestions: [], supporting_examples: [], internal_links: [], schema_review_note: "",
      rationale: "The page never states a duration.", confidence: 0.72 },
    quality: { blocked: false, label: "AI-generated recommendation, not a verified fact", checks: [{ check: "Figures supported by the page", status: "pass", detail: "every figure appears on the page" }] },
    confidence: 0.72, edited_by_user: false, label: "AI-generated recommendation, not a verified fact. Review every claim before adding it to your page.",
    recommendation: { id: "r1", status: "open", priority: "high", difficulty: "low", problem: "p", recommended_action: "a", expected_benefit: "May make the page more useful. (estimate)", requires_approval: true, validation_method: "v" },
    execution: { automated: false, reason: "RankPilot's CMS integrations cannot insert page body content. Add the approved text in your CMS, then mark it implemented." },
    implemented_at: null, implementation_note: null, live_check: null, ...over,
  };
}

class FakeSearch {
  calls: { method: string; path: string; query: URLSearchParams; body: Json | null }[] = [];
  items: Json[] = [opportunity()];
  total = 1;
  summaryRows = 9;
  listFail = false;
  finding: Json | null = null;
  analyzeResult: Json = finding();
  blocked = false;
  implementedLive: boolean | null = true;

  requests(method: string, part: string) { return this.calls.filter((c) => c.method === method && c.path.includes(part)); }

  async install(page: Page) {
    await page.route("**/ai-search/**", (route) => this.handle(route));
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" }, body: JSON.stringify(body) });
  }

  private async handle(route: Route) {
    const req = route.request();
    if (req.method() === "OPTIONS") return this.json(route, {}, 204);
    const url = new URL(req.url());
    let body: Json | null = null;
    try { body = req.postDataJSON() as Json | null; } catch { body = null; }
    this.calls.push({ method: req.method(), path: url.pathname, query: url.searchParams, body });
    const p = url.pathname;
    if (p.endsWith("/summary")) {
      return this.json(route, { window: { start: "2026-10-18", end: "2026-11-14" }, data_coverage: { first_day: "2026-10-18", last_day: "2026-11-14", rows: this.summaryRows },
        warnings: this.summaryRows ? ["Search Console does not return anonymised or very rare queries, so some long-tail searches never appear."] : ["No Search Console data is stored for this project yet. Connect Search Console and sync first."],
        explanation: "These are Google Search queries from Search Console, not prompts typed into ChatGPT, Gemini or other AI tools.",
        totals: { conversational_queries: 1, question_queries: 1, long_tail_queries: 1, comparison_queries: 0, problem_solution_queries: 0, classified_queries: 1, high_opportunity: 1, potential_content_gaps: 0, pages_with_opportunities: 1 },
        ai_platform_visibility: "unmeasured" });
    }
    if (p.endsWith("/opportunities")) {
      if (this.listFail) return this.json(route, { detail: "Database unavailable" }, 500);
      return this.json(route, { items: this.items, page: 1, page_size: 25, total: this.items.length, pages: 1, warnings: [], explanation: "" });
    }
    if (p.endsWith("/opportunities/detail")) {
      return this.json(route, { opportunity: this.items[0] ?? opportunity(), history: [{ date: "2026-11-01", impressions: 25, clicks: 0, average_position: 8 }, { date: "2026-11-02", impressions: 75, clicks: 0, average_position: 8 }], finding: this.finding });
    }
    if (p.endsWith("/analyze")) { this.finding = this.analyzeResult; return this.json(route, this.finding); }
    if (p.endsWith("/draft")) {
      this.finding = finding({ edited_by_user: true, draft: { ...(this.finding!.draft as Json), direct_answer: body!.direct_answer }, quality: { blocked: false, label: "x", checks: [{ check: "Figures supported by the page", status: "pass", detail: "ok" }] } });
      return this.json(route, this.finding);
    }
    if (p.endsWith("/approve")) { this.finding = { ...this.finding!, status: "approved" }; return this.json(route, this.finding); }
    if (p.endsWith("/reject")) { this.finding = { ...this.finding!, status: "rejected" }; return this.json(route, this.finding); }
    if (p.endsWith("/mark-implemented") || p.endsWith("/recheck")) {
      this.finding = { ...this.finding!, status: this.implementedLive ? "monitoring" : "validation_failed", implemented_at: "2026-11-10T10:00:00Z", implementation_note: (body?.note as string) ?? null,
        live_check: { matched: this.implementedLive, error: null, checked_at: "2026-11-10T10:00:01Z" } };
      return this.json(route, this.finding);
    }
    if (p.endsWith("/monitoring")) {
      return this.json(route, { implemented_on: "2026-11-10", window_days: 28, caveat: "A before/after difference does not show that the change caused it.", note: "A before/after difference is a correlation, not proof that this change caused it.",
        after_window_complete: false, before: { clicks: 5, impressions: 200, ctr: 0.025, average_position: 8 }, after: { clicks: 10, impressions: 200, ctr: 0.05, average_position: 5 },
        change: { clicks: 5, impressions: 0, ctr: 0.025, average_position: -3 }, other_changes_in_window: [] });
    }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

async function open(page: Page, search: FakeSearch) {
  const api = new FakeApi({ target_country: null, additional_target_countries: [] });
  await api.install(page);
  await search.install(page);
  await page.goto(PAGE_URL);
  await page.getByRole("button", { name: "AI Search Opportunities" }).click();
  await expect(page.getByTestId("ai-search")).toBeVisible();
}

test("the tab shows real totals, the honest explanation and the opportunity table", async ({ page }) => {
  const search = new FakeSearch();
  await open(page, search);
  const root = page.getByTestId("ai-search");
  await expect(root.getByText("not prompts typed into ChatGPT")).toBeVisible();
  await expect(root.getByText("Question-based queries")).toBeVisible();
  const row = root.getByRole("row", { name: new RegExp(QUERY) });
  await expect(row).toContainText("High opportunity");
  await expect(row).toContainText("/inpatient");
  await expect(row).toContainText("82");
  await expect(row).toContainText("8.0");
  await expect(root.getByText("anonymised or very rare queries")).toBeVisible();
});

test("filters are sent to the server, including a custom date range", async ({ page }) => {
  const search = new FakeSearch();
  await open(page, search);
  const root = page.getByTestId("ai-search");
  await root.getByLabel("Category").selectOption("comparison");
  await root.getByLabel("Min impressions").fill("50");
  await root.getByLabel("Period").selectOption("custom");
  await root.getByLabel("From", { exact: true }).fill("2026-10-01");
  await root.getByLabel("To", { exact: true }).fill("2026-10-31");
  await expect.poll(() => search.requests("GET", "/opportunities").some((c) =>
    c.query.get("category") === "comparison" && c.query.get("min_impressions") === "50" && c.query.get("range") === "custom" &&
    c.query.get("start") === "2026-10-01" && c.query.get("end") === "2026-10-31")).toBe(true);
});

test("with no stored data the page says so instead of showing zeros as results", async ({ page }) => {
  const search = new FakeSearch();
  search.items = [];
  search.summaryRows = 0;
  await open(page, search);
  await expect(page.getByTestId("ai-search-empty")).toContainText("No Search Console data is stored");
});

test("a failed load shows the error and recovers on retry", async ({ page }) => {
  const search = new FakeSearch();
  search.listFail = true;
  await open(page, search);
  await expect(page.getByTestId("ai-search-error")).toContainText("Database unavailable");
  search.listFail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("row", { name: new RegExp(QUERY) })).toBeVisible();
});

test("generate, review, approve, implement and verify, then see monitoring with its caveat", async ({ page }) => {
  const search = new FakeSearch();
  await open(page, search);
  await page.getByRole("button", { name: QUERY }).click();
  const dialog = page.getByRole("dialog", { name: /Query details/ });
  await expect(dialog.getByText("Why this score")).toBeVisible();
  await dialog.getByRole("button", { name: "Generate Content Improvement Recommendation" }).click();

  await expect(dialog.getByLabel("Direct answer")).toHaveValue(/28 to 90 days/);
  await expect(dialog.getByText("AI-generated recommendation, not a verified fact", { exact: false }).first()).toBeVisible();
  await expect(dialog.getByTestId("quality-checks")).toContainText("Figures supported by the page");
  await expect(dialog.getByText("AI-platform visibility:")).toContainText("unmeasured");
  await expect(dialog.getByTestId("execution-note")).toContainText("cannot insert page body content");
  expect(search.requests("POST", "/analyze")[0].body).toMatchObject({ query: QUERY });

  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(dialog.getByText("Approved. Add the text to your page in your CMS")).toBeVisible();
  await dialog.getByLabel("Note (optional)").fill("added under the intro");
  await dialog.getByRole("button", { name: "Mark as implemented" }).click();
  await expect(dialog.getByTestId("live-check")).toContainText("The public page now shows the change.");
  expect(search.requests("POST", "/mark-implemented")[0].body).toEqual({ note: "added under the intro" });

  const monitoring = dialog.getByTestId("monitoring");
  await expect(monitoring).toContainText("does not show that the change caused it");
  await expect(monitoring).toContainText("not complete yet");
  await expect(monitoring.getByRole("row", { name: /before/ })).toContainText("200");
});

test("editing the answer sends only the edit and re-runs the checks on the server", async ({ page }) => {
  const search = new FakeSearch();
  await open(page, search);
  await page.getByRole("button", { name: QUERY }).click();
  const dialog = page.getByRole("dialog", { name: /Query details/ });
  await dialog.getByRole("button", { name: "Generate Content Improvement Recommendation" }).click();
  await dialog.getByLabel("Direct answer").fill("Most inpatient programmes run for 28 to 90 days with weekly clinical review of the plan.");
  await dialog.getByRole("button", { name: "Save edits and re-check" }).click();
  await expect.poll(() => search.requests("PATCH", "/draft").length).toBe(1);
  expect(search.requests("PATCH", "/draft")[0].body).toMatchObject({ direct_answer: expect.stringContaining("weekly clinical review") });
});

test("a draft that fails a quality check cannot be approved", async ({ page }) => {
  const search = new FakeSearch();
  search.analyzeResult = finding({ quality: { blocked: true, label: "x", checks: [{ check: "Figures supported by the page", status: "fail", detail: "not found on the page: 95%" }] } });
  await open(page, search);
  await page.getByRole("button", { name: QUERY }).click();
  const dialog = page.getByRole("dialog", { name: /Query details/ });
  await dialog.getByRole("button", { name: "Generate Content Improvement Recommendation" }).click();
  await expect(dialog.getByTestId("quality-checks")).toContainText("not found on the page: 95%");
  await expect(dialog.getByRole("button", { name: "Approve" })).toBeDisabled();
});

test("when the AI is unavailable the analysis still shows and no draft is offered", async ({ page }) => {
  const search = new FakeSearch();
  search.analyzeResult = finding({ draft: null, quality: null, recommendation: null, status: "new", ai_status: "unavailable", ai_error: "The daily AI budget for this project has been used." });
  await open(page, search);
  await page.getByRole("button", { name: QUERY }).click();
  const dialog = page.getByRole("dialog", { name: /Query details/ });
  await dialog.getByRole("button", { name: "Generate Content Improvement Recommendation" }).click();
  await expect(dialog.getByTestId("ai-note")).toContainText("daily AI budget");
  await expect(dialog.getByText("Does the page answer it?")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Approve" })).toHaveCount(0);
});

test("a failed verification is reported and can be re-checked", async ({ page }) => {
  const search = new FakeSearch();
  search.implementedLive = false;
  await open(page, search);
  await page.getByRole("button", { name: QUERY }).click();
  const dialog = page.getByRole("dialog", { name: /Query details/ });
  await dialog.getByRole("button", { name: "Generate Content Improvement Recommendation" }).click();
  await dialog.getByRole("button", { name: "Approve" }).click();
  await dialog.getByRole("button", { name: "Mark as implemented" }).click();
  await expect(dialog.getByTestId("live-check")).toContainText("does not show the change yet");
  search.implementedLive = true;
  await dialog.getByRole("button", { name: "Check the page again" }).click();
  await expect(dialog.getByTestId("live-check")).toContainText("The public page now shows the change.");
});

test("competing pages are called out before anything is changed", async ({ page }) => {
  const search = new FakeSearch();
  search.items = [opportunity({ needs_review: true, other_pages: [{ page_id: "p2", url: "https://clinic.example/detox", impressions: 40 }] })];
  await open(page, search);
  await expect(page.getByRole("row", { name: new RegExp(QUERY) })).toContainText("pages compete");
  await page.getByRole("button", { name: QUERY }).click();
  await expect(page.getByRole("dialog").getByText("https://clinic.example/detox")).toBeVisible();
});
