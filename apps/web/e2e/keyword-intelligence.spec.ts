import { expect, test } from "@playwright/test";
import { FakeApi, ORG, SITE, recommendation } from "./support/fakeApi";

const URL = `/dashboard/websites/${SITE}/keywords`;

async function open(page: import("@playwright/test").Page, api: FakeApi) {
  await api.install(page);
  await page.goto(URL);
  await expect(page.getByRole("heading", { name: "Keyword Intelligence" })).toBeVisible();
}

test.describe("country selection", () => {
  test("the project's primary country pre-selects the workspace and scopes the requests", async ({ page }) => {
    const api = new FakeApi({ target_country: "PK", additional_target_countries: ["GB"] });
    await open(page, api);

    await expect(page.locator("#country-filter")).toHaveValue("PK");
    const options = await page.locator("#country-filter option").allTextContents();
    expect(options).toEqual(["All countries", "Pakistan (PK)", "United Kingdom (GB)"]);
    await expect.poll(() => api.requests("GET", "search-performance/intelligence").some((c) => c.path.includes("country=PK"))).toBe(true);

    await page.locator("#country-filter").selectOption("GB");
    await expect.poll(() => api.requests("GET", "search-performance/intelligence").some((c) => c.path.includes("country=GB"))).toBe(true);
  });

  test("with no target country the workspace starts on all countries", async ({ page }) => {
    const api = new FakeApi({ target_country: null, additional_target_countries: [] });
    await open(page, api);
    await expect(page.locator("#country-filter")).toHaveValue("");
    expect(api.requests("GET", "search-performance/intelligence").every((c) => !c.path.includes("country="))).toBe(true);
  });
});

test.describe("target market settings", () => {
  test("add a country, set a market language, save, and see it again after reloading", async ({ page }) => {
    const api = new FakeApi({ target_country: "PK", additional_target_countries: ["GB"] });
    await open(page, api);

    await page.locator("#tm-add").selectOption("CA");
    await page.getByRole("button", { name: "Add country" }).click();
    await page.getByLabel("Language for Pakistan").selectOption("ur");
    await page.getByLabel("City / region (optional)").fill("Rawalpindi");
    await page.getByRole("button", { name: "Save target market" }).click();

    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
    const [patch] = api.requests("PATCH", "/settings");
    expect(patch.body).toMatchObject({
      target_country: "PK",
      additional_target_countries: ["GB", "CA"],
      target_city: "Rawalpindi",
      target_languages_by_country: { PK: "ur" },
    });
    // the country selector immediately reflects the new market
    await expect(page.locator("#country-filter option")).toHaveText(["All countries", "Pakistan (PK)", "United Kingdom (GB)", "Canada (CA)"]);

    await page.reload();
    await expect(page.getByLabel("Language for Pakistan")).toHaveValue("ur");
    await expect(page.getByRole("cell", { name: "Canada (CA)" })).toBeVisible();
  });

  test("remove a country", async ({ page }) => {
    const api = new FakeApi({ target_country: "PK", additional_target_countries: ["GB", "CA"], target_languages_by_country: { GB: "en" } });
    await open(page, api);

    await page.getByRole("button", { name: "Remove United Kingdom" }).click();
    await expect(page.getByRole("cell", { name: "United Kingdom (GB)" })).toHaveCount(0);
    await page.getByRole("button", { name: "Save target market" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();

    const [patch] = api.requests("PATCH", "/settings");
    expect(patch.body?.additional_target_countries).toEqual(["CA"]);
    expect(patch.body?.target_languages_by_country).toEqual({});
  });

  test("the primary country cannot also be added as an additional one", async ({ page }) => {
    const api = new FakeApi({ target_country: "PK", additional_target_countries: [] });
    await open(page, api);
    const additional = await page.locator("#tm-add option").allTextContents();
    expect(additional.some((t) => t.includes("Pakistan"))).toBe(false);
  });

  test("a rejected save shows the server's reason and no success message", async ({ page }) => {
    const api = new FakeApi({ settingsError: "Unknown country code 'QQQ'." });
    await open(page, api);
    await page.getByRole("button", { name: "Save target market" }).click();
    await expect(page.locator('p[role="alert"]')).toContainText("Unknown country code");
    await expect(page.getByText("Saved.")).toHaveCount(0);
  });
});

test.describe("AI discovery and competitor analysis", () => {
  test("when the AI step fails the reason is shown and first-party ideas are still listed", async ({ page }) => {
    const api = new FakeApi({
      discoveryResponse: { ideas: [], freshness_note: "", ai_status: "invalid_response",
        ai_message: "The AI returned a response RankPilot could not use, so no AI ideas were added." },
    });
    await open(page, api);
    await page.getByRole("button", { name: "AI Discovery", exact: true }).click();
    await page.getByRole("button", { name: "Run discovery" }).click();
    await expect(page.getByRole("status")).toContainText("could not use");
    await expect(page.getByRole("status")).toContainText("still listed below");
  });

  test("a successful discovery says how many ideas it found", async ({ page }) => {
    const api = new FakeApi();
    await open(page, api);
    await page.getByRole("button", { name: "AI Discovery", exact: true }).click();
    await page.getByRole("button", { name: "Run discovery" }).click();
    await expect(page.getByRole("status")).toContainText("Discovery finished: 0 ideas");
  });

  test("competitor analysis reports the crawl even when the AI step did not run", async ({ page }) => {
    const api = new FakeApi({
      analyzeResponse: { ideas: [], pages_fetched: 2, pages_failed: 3, ai_status: "unavailable",
        ai_message: "The AI provider timed out, so no AI ideas were added. Try again in a few minutes." },
    });
    await open(page, api);
    await page.getByRole("button", { name: "Competitor Gaps", exact: true }).click();
    await page.getByRole("button", { name: /^Analyze/ }).click();
    const note = page.getByRole("status");
    await expect(note).toContainText("Fetched 2 public pages (3 could not be fetched)");
    await expect(note).toContainText("timed out");
  });
});

test.describe("growth recommendations", () => {
  test("generating with no qualifying signals explains why", async ({ page }) => {
    const api = new FakeApi({ recommendationsToGenerate: [] });
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();
    await expect(page.getByRole("status")).toContainText("Nothing to recommend for PK yet");
    await expect(page.getByRole("status")).toContainText("positions 11-20");
  });

  test("generating reports the count, and unsupported types say why they cannot be automated", async ({ page }) => {
    const api = new FakeApi({
      recommendationsToGenerate: [
        recommendation({ id: "rec-new", recommendation_type: "create_blog_post", title: "Create blog_post for knee pain", automation_available: false }),
      ],
    });
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();
    await expect(page.getByRole("status")).toContainText("1 recommendation generated for PK");
    await expect(page.getByTestId("unsupported-reason")).toContainText("no automated change for this kind of recommendation");
  });

  test("raw type names and evidence JSON are shown as readable text", async ({ page }) => {
    const api = new FakeApi({
      recommendationsToGenerate: [
        recommendation({
          id: "rec-idea", recommendation_type: "create_blog_post", automation_available: false,
          title: 'Create blog_post for "knee pain exercises"',
          recommended_action: "Plan and write original blog_post covering this topic.",
          evidence_json: { keyword_idea_id: "4305e08a-1aec-47d3-a470-63262b2f3cda", confidence: 0.85, data_classification: "ai_generated_idea" },
        }),
        recommendation({ id: "rec-gsc", title: "Strengthen the page", evidence_json: { impressions: 150, average_position: 14.2, window_days: 28 } }),
      ],
    });
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();

    await expect(page.getByText('Create blog post for "knee pain exercises"')).toBeVisible();
    await expect(page.getByText("Plan and write original blog post covering this topic.")).toBeVisible();
    await expect(page.getByText(/AI confidence 85%.*AI-generated idea \(not verified demand\)/)).toBeVisible();
    await expect(page.getByText("150 impressions · average position 14.2 · last 28 days")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("keyword_idea_id");
    await expect(page.locator("body")).not.toContainText("blog_post");
  });

  test("without a connected CMS the reason is shown instead of an apply button", async ({ page }) => {
    const api = new FakeApi({ cmsConnected: false, recommendationsToGenerate: [recommendation({ status: "approved" })] });
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();
    await expect(page.getByTestId("unsupported-reason")).toContainText("No CMS is connected");
    await expect(page.getByRole("button", { name: "Prepare AI draft change" })).toHaveCount(0);
  });

  test("a recommendation marked done by hand is labelled as applied manually", async ({ page }) => {
    const api = new FakeApi({ cmsConnected: false, recommendationsToGenerate: [recommendation({ status: "open" })] });
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await page.getByRole("button", { name: /Mark as done/ }).click();
    await expect(page.getByText("applied (manually)").first()).toBeVisible();
  });

  async function walkToApplied(page: import("@playwright/test").Page, api: FakeApi) {
    await open(page, api);
    await page.getByRole("button", { name: "Recommendations", exact: true }).click();
    await page.getByRole("button", { name: "Generate from current data" }).click();

    await page.getByRole("button", { name: "Approve", exact: true }).click(); // the recommendation
    await page.getByRole("button", { name: "Prepare AI draft change" }).click();
    await expect(page.getByText("Knee Pain Treatment | Example Clinic").first()).toBeVisible();

    await page.getByRole("button", { name: "Preview before / after" }).click();
    await expect(page.getByRole("cell", { name: "Old title" })).toBeVisible();

    await page.getByRole("button", { name: "Approve change" }).click();
    await page.getByRole("button", { name: "Apply to site" }).click();
  }

  test("supported change: preview, approve, apply, then the verification crawl confirms it", async ({ page }) => {
    await page.clock.install();
    const api = new FakeApi({ recommendationsToGenerate: [recommendation()], recrawlOutcome: "validated" });
    await walkToApplied(page, api);

    // applied, CMS read-back passed, crawl queued: validation is still pending
    await expect(page.getByTestId("recrawl-status")).toContainText("Re-crawl queued");
    await expect(page.getByLabel("Execution status").getByText("Validation pending").first()).toBeVisible();

    // the page checks back on its own; the crawl then confirms the value
    await page.clock.fastForward(6000);
    await expect(page.getByTestId("recrawl-status")).toContainText("Re-crawl confirmed");
    await expect(page.getByLabel("Execution status").getByText("Validated", { exact: true }).first()).toBeVisible();

    expect(api.requests("POST", "/tasks/task-1/approve")).toHaveLength(1);
    expect(api.requests("POST", "/tasks/task-1/execute")).toHaveLength(1);
    // nothing was applied before the explicit approvals
    const order = api.calls.filter((c) => c.method === "POST").map((c) => c.path.split("/").slice(-1)[0]);
    expect(order.indexOf("approve")).toBeLessThan(order.indexOf("execute"));
    expect(order.indexOf("dry-run")).toBeLessThan(order.indexOf("execute"));
  });

  test("when the crawl does not see the change, it stays pending with the reason and can be re-crawled", async ({ page }) => {
    await page.clock.install();
    const api = new FakeApi({ recommendationsToGenerate: [recommendation()], recrawlOutcome: "mismatch" });
    await walkToApplied(page, api);

    await page.clock.fastForward(6000);
    await expect(page.getByTestId("recrawl-status")).toContainText('did not see the change yet (found "Old title")');
    await expect(page.getByLabel("Execution status").getByText("Validation pending").first()).toBeVisible();
    await expect(page.getByLabel("Execution status").getByText("Failed")).toHaveCount(0);

    await page.getByRole("button", { name: "Re-crawl page" }).click();
    await expect(page.getByTestId("recrawl-status")).toContainText("Re-crawl queued");
    expect(api.requests("POST", "/recrawl")).toHaveLength(1);
  });

  test("a failed verification crawl is reported without calling the applied change failed", async ({ page }) => {
    await page.clock.install();
    const api = new FakeApi({ recommendationsToGenerate: [recommendation()], recrawlOutcome: "failed" });
    await walkToApplied(page, api);
    await page.clock.fastForward(6000);
    await expect(page.getByTestId("recrawl-status")).toContainText("could not verify the change: The page returned HTTP 500.");
    await expect(page.getByLabel("Execution status").getByText("Validation pending").first()).toBeVisible();
  });
});

test.describe("performance", () => {
  test("GA4 landing sessions sit in their own column, labelled as engagement not ranking", async ({ page }) => {
    const entry = {
      change_id: "c1", page_id: "p1", page_url: "https://clinic.example/knee", operation: "set_title",
      implemented_at: "2026-11-01T00:00:00Z", validation_status: "passed", after_window_complete: true,
      before: { clicks: 2, impressions: 100, ctr: 0.02, average_position: 12 },
      after: { clicks: 10, impressions: 200, ctr: 0.05, average_position: 8 },
      organic_landing_before: { sessions: 3, engaged_sessions: 2, conversions: 0 },
      organic_landing_after: { sessions: 8, engaged_sessions: 6, conversions: 1 },
      site_ga4_before: null, site_ga4_after: null,
    };
    const api = new FakeApi({ timeline: { window_days: 28, caveat: "Correlation, not proof.", entries: [entry] } });
    await open(page, api);
    await page.getByRole("button", { name: "Performance", exact: true }).click();
    const row = page.getByRole("row", { name: /clinic.example\/knee/ });
    await expect(row).toContainText("2 → 10"); // Search Console clicks
    await expect(row).toContainText("3 → 8"); // GA4 organic landing sessions
    await expect(row).toContainText("GA4 engagement, not a ranking metric");
    await expect(page.getByRole("columnheader", { name: "GA4 organic landing sessions" })).toBeVisible();
  });
});

// keep the org id referenced so a rename of the constant is caught here
test("fixtures use the expected ids", () => {
  expect(ORG).toMatch(/^0{8}-/);
});
