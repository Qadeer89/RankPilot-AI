/**
 * Not part of the normal suite: run with CAPTURE_MARKETING=1 to regenerate the product screenshots used on the public website
 * (public/screens/*.jpg). They are the REAL application pages rendered with SAMPLE data for a fictional "Example Clinic"; the
 * marketing pages label them as sample data. Nothing here is a customer's data.
 */
import { test, type Page, type Route } from "@playwright/test";
import { ORG, SITE } from "./support/fakeApi";

test.skip(!process.env.CAPTURE_MARKETING, "set CAPTURE_MARKETING=1 to regenerate marketing screenshots");

type J = Record<string, unknown>;
const OUT = "public/screens";
const iso = (d: number) => new Date(Date.UTC(2026, 10, 24 - d, 10)).toISOString();
const HOST = "https://clinic.example";

const website: J = { id: SITE, organization_id: ORG, canonical_url: `${HOST}/`, hostname: "clinic.example", display_name: "Example Clinic", verification_status: "verified", platform: "wordpress", crawl_budget: 300,
  status: "active", automation_policy: {}, automation_mode: "copilot", crawl_frequency_hours: 24, ai_daily_budget_usd_override: null, search_console_site_url: "sc-domain:clinic.example", ga4_property_id: "properties/1",
  target_country: "PK", additional_target_countries: ["GB"], target_language: "en", target_city: null, target_languages_by_country: {} };
const slugs = ["", "services", "services/knee-pain", "services/back-pain", "services/sports-injury", "blog", "blog/knee-pain-on-stairs", "blog/frozen-shoulder-recovery", "blog/desk-ergonomics", "about", "contact"];
const pages = slugs.map((s, i) => ({ id: `p${i}`, website_id: SITE, canonical_url: `${HOST}/${s}`, normalized_url: `${HOST}/${s}`, last_status_code: 200, indexability_state: "indexable", first_seen_at: iso(30), last_seen_at: iso(1) }));
const finding = (id: string, page: string, rule: string, severity: string, evidence: J) => ({ id, website_id: SITE, page_id: page, rule_code: rule, severity, confidence: 0.7, evidence_json: evidence, first_detected_at: iso(9), last_detected_at: iso(1), status: "open" });
const findings = [
  ...pages.slice(0, 8).map((p, i) => finding(`r${i}`, p.id, "EXTERNAL_LINK_REDIRECT", "info", { count: 1, urls: ["https://wa.me/920000000000"] })),
  ...[2, 3, 6, 7, 8].map((i) => finding(`t${i}`, `p${i}`, "TITLE_TOO_LONG", "info", { length: 68 + i, threshold: 60 })),
  finding("h1", "p6", "HEADING_HIERARCHY_SKIP", "info", { sequence: [1, 3, 2, 3] }),
  finding("th", "p10", "THIN_CONTENT", "warning", { word_count: 90, threshold: 300, page_type: "contact" }),
];
const score = (n: number, overall: number) => ({ id: `s${n}`, website_id: SITE, crawl_job_id: `c${n}`, overall_score: overall, technical_score: overall + 2, on_page_score: overall + 1, content_score: 100, performance_score: 76, critical_count: 0, warning_count: 1, info_count: 14 - n, passed_count: 420, created_at: iso(n * 3) });
const scores = [score(0, 91), score(1, 89), score(2, 86), score(3, 82), score(4, 74), score(5, 62)];
const crawls = [0, 1, 2].map((n) => ({ id: `c${n}`, website_id: SITE, trigger: "scheduled", status: "completed", started_at: iso(n * 3), completed_at: iso(n * 3), pages_requested: 11, pages_fetched: 11, error_summary: null }));
const opportunities = [
  { id: "o1", website_id: SITE, page_id: "p2", category: "on_page", title: "Shorten the title of “Knee pain treatment”", rationale: "The title is cut off in search results.", impact_estimate: 0.6, confidence: 0.8, effort_estimate: 0.1, risk_tier: 1, score: 78, status: "open" },
  { id: "o2", website_id: SITE, page_id: "p5", category: "technical", title: "Fix a link that redirects", rationale: "A shared header link sends visitors through a redirect.", impact_estimate: 0.4, confidence: 0.9, effort_estimate: 0.1, risk_tier: 1, score: 66, status: "open" },
];

const AUTH = { disclaimer: "RankPilot's Domain Quality is calculated from your own crawl and search data. It is not Domain Rating, Domain Authority, Authority Score, Trust Flow or Citation Flow, it does not measure links from other websites, and it is not a Google score.", empty_reason: null, comparison: { available: true, domain_quality_change: 3.4, note: null, signals: [] }, history: [] };
const sig = (key: string, label: string, value: number | null, weight: number, how: string, note: string | null = null) => ({ key, label, value, weight, status: value === null ? "not_available" : "calculated", how, inputs: {}, note });
const authority = { ...AUTH, latest: { id: "a1", computed_at: iso(1), formula_version: "authority-v1", domain_quality: 82.4, coverage: 0.9, confidence: "high", data_source: "RankPilot calculated", inputs: {}, signals: [
  sig("internal_link_strength", "Internal Link Strength", 88, 0.2, "60% pages that have at least one internal link pointing to them + 40% pages with 3 or more."),
  sig("content_coverage", "Content Coverage", 81, 0.15, "70% pages with at least 300 words + 30% pages not sharing identical content."),
  sig("crawl_health", "Crawl Health", 96, 0.15, "60% pages answering with a 2xx status + 40% pages without a broken internal link."),
  sig("indexability_health", "Indexability Health", 100, 0.15, "Share of 2xx pages that search engines are allowed to index."),
  sig("topical_consistency", "Topical Consistency", 73, 0.1, "Share of pages whose title or H1 uses one of the site's own most common terms."),
  sig("organic_visibility", "Organic Visibility", 64, 0.1, "Share of indexable pages that had at least one Search Console impression in 28 days."),
  sig("structure_quality", "Website Structure Quality", 79, 0.1, "70% pages reachable within 3 clicks of the home page + 30% depth penalty."),
  sig("content_freshness", "Content Freshness", null, 0.05, "Share of pages whose content changed between crawls.", "Needs 30 days of crawl history (have 12)."),
] } };
const bl = (id: string, url: string, anchor: string | null, status: string, nofollow: boolean | null) => ({ id, source_url: url, source_domain: new URL(url).hostname, target_url: status === "live" ? `${HOST}/services/knee-pain` : null, anchor_text: anchor, rel_values: nofollow ? ["nofollow"] : [], is_nofollow: nofollow, link_location: status === "live" ? "content" : null,
  discovery_source: "user_provided", status, http_status: status === "unchecked" ? null : 200, first_discovered_at: iso(8), last_checked_at: status === "unchecked" ? null : iso(1), last_live_at: status === "live" ? iso(1) : null, lost_at: null, note: null, data_source: status === "live" ? "Verified from the source page" : "Not checked" });
const backlinks = { items: [bl("b1", "https://health-blog.example/knee-guide", "knee pain physiotherapy", "live", false), bl("b2", "https://local-directory.example/clinics", "Example Clinic", "live", true), bl("b3", "https://news.example/story", null, "unchecked", null)],
  analysis: { label: "Verified from the source pages you listed. This is not a count of every link to your site; RankPilot has no web-wide link index.", recorded: 3, verified_live: 2, by_status: {}, unchecked: 1, referring_domains: 2, followed: 1, nofollow_or_ugc_sponsored: 1, top_domains: [], anchor_distribution: [{ anchor: "knee pain physiotherapy", links: 1, share: 0.5 }, { anchor: "example clinic", links: 1, share: 0.5 }], destination_pages: [], single_domain_share: 0.5, lost: [] },
  limits: { max_import: 500, max_checks_per_call: 25 }, empty_reason: null };

const chk = (key: string, label: string, status: string, detail: string, group = "technical") => ({ key, label, status, detail, group });
const technical = { latest: { computed_at: iso(1), formula_version: "technical-health-v1", score: 78.6, coverage: 0.9, available: true, data_source: "Verified (fetched from your site) + RankPilot calculated", checks: [
  chk("homepage_fetch", "Homepage reachable", "pass", "HTTP 200"), chk("html_lang", "Page language declared (html lang)", "pass", 'lang="en"'), chk("open_graph", "Open Graph tags (social previews)", "warn", "Missing: og:image."),
  chk("canonical_host_http", "Http version redirects to the canonical address", "pass", "http://clinic.example/ ends at https://clinic.example/."), chk("robots_txt", "robots.txt present", "pass", "HTTP 200"), chk("sitemap_xml", "sitemap.xml present", "pass", "HTTP 200"),
  chk("structured_data", "Structured data required properties", "warn", "6 pages with markup; 1 with missing required properties.", "structured_data"), chk("hreflang", "hreflang annotations", "not_tested", "None found. Only needed if the site has language or country versions."),
  chk("hdr_hsts", "HSTS header", "warn", "Not sent. Hygiene signal, not a ranking factor.", "security_hygiene"),
], note: "" }, history: [], empty_reason: null };

const profile = { exists: true, confirmed: true, business_type: "physiotherapy clinic", industry: "Healthcare", offerings: ["Knee pain therapy", "Back pain therapy", "Sports injury rehabilitation"], target_customers: ["Office workers", "Athletes"], objective: "More appointment requests", known_competitors: [], ai_suggestions: null, confirmed_at: iso(10), target_countries: ["PK", "GB"] };
const journey = { mode: "progress", message: "You have a saved starting point and 6 analyses since. Here is what is verified, what is still open and what comes next.", baseline: { taken_at: iso(15), reconstructed: false }, last_analysis_at: iso(1),
  integrations: { google_search_console: { connected: true, has_data: true }, ga4: { connected: true, has_data: true }, cms: "wordpress" },
  panels: [{ panel: "Website health and issues", available: true, source: "RankPilot crawl", reason: null }, { panel: "Organic clicks, impressions, position", available: true, source: "Google Search Console", reason: null }, { panel: "Organic landing sessions", available: true, source: "Google Analytics 4", reason: null }],
  next_actions: [{ key: "a", text: "Fix the shared header link that redirects", detail: "One edit clears 8 findings." }, { key: "b", text: "Shorten 5 page titles", detail: null }], recommendations: { total: 7, by_priority: { high: 2, medium: 3, low: 2 }, by_type: {}, by_stage: {} }, expectations: "No result, ranking or traffic level is guaranteed." };
const plan = { generated_from: { pages: 11, open_issues: 15, critical_issues: 0, open_recommendations: 7 }, size_class: "small", pace_note: "With 11 pages, much of this can finish sooner than 30 days.", disclaimer: "Completing it does not guarantee higher rankings.", generated_at: iso(1),
  stages: [{ days: "1-3", title: "Discovery and baseline", items: [{ text: "Confirm your business profile", status: "done", basis: "Saved with your offerings and target customers.", count: null }, { text: "Connect Google Search Console", status: "done", basis: "Connected, so search performance is verified.", count: null }] },
    { days: "4-14", title: "Fix what is holding pages back", items: [{ text: "Shorten page titles that are cut off", status: "todo", basis: "5 titles are longer than search results show.", count: 5 }, { text: "Fix the header link that redirects", status: "todo", basis: "The same link appears on 8 pages.", count: 8 }] }] };
const rec = (id: string, title: string, priority: string, type: string, problem: string) => ({ id, kind: "seo_opportunity", title, affected: `${HOST}/services/knee-pain`, type, problem, evidence: {}, why_it_matters: "Clear titles help people choose your result.", suggested_solution: "Shorten it", implementation: "Review, approve and apply", priority, effort: "low", benefit_category: "x", validation: "RankPilot re-reads the live page to confirm.", stage: "recommended", actions: ["approve"], data_source: "RankPilot crawl" });
const recs = [rec("r1", "Shorten the title of “Knee pain treatment”", "high", "on_page", "The title is 74 characters; search results show about 60."), rec("r2", "Fix a header link that redirects", "medium", "technical", "The same link is on 8 pages and sends visitors through a redirect."), rec("r3", "Cover “sports injury rehabilitation” in a dedicated page", "medium", "content", "Your offerings include it, but no page title or heading covers it.")];

const H_BASE = { id: "s-base", taken_at: iso(45), type: "crawl", is_baseline: true, status: "completed", reconstructed: false, analysis_version: "rules-2026.11", scoring_version: "health-v1", partial_reason: null, health_overall: 62, open_issues: 65, pages_crawled: 40 };
const H_LAST = { ...H_BASE, id: "s-last", taken_at: iso(1), is_baseline: false, health_overall: 91, open_issues: 15, pages_crawled: 143 };
const histOverview = { baseline: H_BASE, latest: H_LAST, health: { initial: 62, current: 91, previous: 82, change: 29, change_pct: 46.8, status: "improved", note: "RankPilot's own measure of website health. It is not a Google ranking." },
  issues: { identified_total: 80, resolved: 65, still_open: 15, new_since_baseline: 12, note: "" }, work: { pages_optimized: 12, recommendations_implemented: 9, recommendations_validated: 8, recommendations_failed: 0 },
  data_sources: { crawler: { available: true, reason: null }, google_search_console: { available: true, reason: null }, ga4: { available: true, reason: null } }, baseline_performance: { available: false } };
const histCompare = { from: H_BASE, to: H_LAST, comparison_period: { start: "2026-10-10", end: "2026-11-23" }, warnings: [], rows: [
  { group: "Health", label: "Overall SEO health score", source: "RankPilot crawl", previous: 62, current: 91, change: 29, change_pct: 46.8, status: "improved" },
  { group: "Issues", label: "Open issues", source: "RankPilot crawl", previous: 65, current: 15, change: -50, change_pct: -76.9, status: "improved" },
  { group: "Health", label: "Technical score", source: "RankPilot crawl", previous: 70, current: 95, change: 25, change_pct: 35.7, status: "improved" },
  { group: "Health", label: "Performance score", source: "RankPilot crawl", previous: 74, current: 76, change: 2, change_pct: 2.7, status: "unchanged" }], issue_changes: { available: true, resolved: 65, new: 12, still_open: 3 } };

const idea = (id: string, keyword: string, intent: string, source: string, cls: string, conf: number, ctype: string | null, why: string) => ({ id, keyword, search_intent: intent, source, data_classification: cls, country: "PK", language: "en", relevance: conf, confidence: conf,
  recommended_content_type: ctype, target_page_id: null, proposed_title: null, rationale: why, cluster_key: null, status: "new", brand_search: false, created_at: iso(2) });
const ideas = [
  idea("k1", "knee pain physiotherapy", "informational", "seed", "verified_first_party", 1, null, "A real Search Console query for your site."),
  idea("k2", "back pain exercises at home", "informational", "ai_generated", "ai_generated_idea", 0.86, "blog_post", "Fits your back pain therapy page; an AI estimate, not search demand."),
  idea("k3", "sports injury rehabilitation clinic", "commercial", "ai_generated", "ai_generated_idea", 0.82, "service_page", "Listed as an offering, but no page title or heading covers it yet."),
  idea("k4", "frozen shoulder recovery timeline", "informational", "seed", "verified_first_party", 0.5, null, "Found in a page title on your site. This shows what your site says, not that people search for it."),
  idea("k5", "physiotherapy for knee injuries", "commercial", "competitor_gap", "ai_generated_idea", 0.78, "blog_post", "A topic competitor pages cover that your titles and headings do not."),
  idea("k6", "desk ergonomics setup", "informational", "ai_generated", "ai_generated_idea", 0.74, "blog_post", "Related to your existing posture content."),
];

async function route(page: Page, extra: (p: string, q: URLSearchParams) => unknown | undefined) {
  await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "sample"));
  await page.route("**/api/v1/**", (r: Route) => {
    const req = r.request();
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (req.method() === "OPTIONS") return r.fulfill({ status: 204, headers: cors });
    const u = new URL(req.url());
    const p = u.pathname;
    const base = `/websites/${SITE}`;
    let body: unknown = extra(p, u.searchParams);
    if (body === undefined) {
      if (p.endsWith("/me")) body = { user: { id: "u1", email: "owner@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Example Org", slug: "org", role: "owner" }] };
      else if (p.endsWith(base)) body = website;
      else if (p.endsWith(`${base}/pages`)) body = pages;
      else if (p.endsWith(`${base}/findings`)) body = findings;
      else if (p.endsWith(`${base}/crawls`)) body = crawls;
      else if (p.endsWith(`${base}/health-score`)) body = scores;
      else if (p.endsWith(`${base}/opportunities`)) body = opportunities;
      else if (p.endsWith(`${base}/overview`)) body = { pages_discovered: 11, pages_indexed: 9, pages_inspected: 11, indexing_last_checked_at: iso(1), pending_approvals: 0, latest_health_score: scores[0] };
      else if (p.endsWith("/connections")) body = [{ id: "cn1", website_id: SITE, connector_type: "wordpress", status: "connected" }];
      else if (p.endsWith("/keyword-ideas")) body = ideas;
      else if (p.endsWith("/growth-recommendations")) body = [];
      else if (p.endsWith("/ai-usage")) body = { days: 30, by_agent_type: [], total_estimated_cost_usd: 0, note: "" };
      else if (p.endsWith("/performance-timeline")) body = { window_days: 28, caveat: "", entries: [] };
      else if (p.endsWith(`${base}/search-performance`)) body = { source: "google_search_console", freshness_note: "Search Console data lags 2-3 days.", rows: [] };
      else if (p.endsWith("/reference/countries")) body = [{ code: "PK", name: "Pakistan" }, { code: "GB", name: "United Kingdom" }];
      else if (p.endsWith("/search-performance/intelligence")) body = { freshness_note: "Search Console data lags 2-3 days.", country: "PK", declining_pages: [], ranking_improvement_opportunities: [], keyword_cannibalization: [], new_queries: [] };
      else if (p.endsWith(`${base}/competitors`)) body = [{ id: "cp1", domain: "rival.example", last_analyzed_at: iso(3), created_at: iso(10) }];
      else if (p.endsWith(`${base}/tasks`) || p.endsWith(`${base}/reports`) || p.endsWith("/change-records")) body = [];
      else { console.log("UNHANDLED", p); body = { detail: "sample: not needed" }; }
    }
    const status = typeof body === "object" && body && "detail" in (body as J) && Object.keys(body as J).length === 1 ? 404 : 200;
    return r.fulfill({ status, headers: cors, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function shot(page: Page, name: string, ready: () => Promise<unknown>, clip?: { h: number }) {
  await ready();
  await page.addStyleTag({ content: "nextjs-portal, [data-nextjs-dev-tools-button], [data-next-badge-root] { display: none !important; }" });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${name}.jpg`, type: "jpeg", quality: 84, clip: { x: 0, y: 0, width: 1360, height: clip?.h ?? 860 } });
}

test.use({ viewport: { width: 1360, height: 900 } });

test("overview", async ({ page }) => {
  await route(page, () => undefined);
  await page.goto(`/dashboard/websites/${SITE}`);
  await shot(page, "overview", () => page.getByText("Site health").first().waitFor());
});
test("findings", async ({ page }) => {
  await route(page, () => undefined);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Findings", exact: true }).click();
  await page.getByTestId("finding-group").nth(1).getByRole("button").first().click();
  await shot(page, "findings", () => page.getByTestId("shared-link").waitFor());
});
test("growth-plan", async ({ page }) => {
  await route(page, (p) => p.endsWith("/growth/journey") ? journey : p.endsWith("/growth/plan") ? plan : p.endsWith("/business-profile") ? profile
    : p.endsWith("/growth/recommendations") ? { items: recs, page: 1, page_size: 25, total: 3, pages: 1, summary: journey.recommendations } : undefined);
  await page.goto(`/dashboard/websites/${SITE}/growth`);
  await shot(page, "growth-plan", () => page.getByTestId("next-actions").waitFor());
});
test("authority", async ({ page }) => {
  await route(page, (p) => p.endsWith("/authority") ? authority : p.endsWith("/backlinks") ? backlinks : p.endsWith("/ranking-opportunities") ? { available: false, reason: "x", items: [], formula_version: "v1" } : undefined);
  await page.goto(`/dashboard/websites/${SITE}/authority`);
  await shot(page, "authority", () => page.getByTestId("dq-score").waitFor(), { h: 1000 });
});
test("intelligence", async ({ page }) => {
  await route(page, (p) => p.endsWith("/intelligence/technical") ? technical : p.includes("/intelligence/") ? { latest: null, history: [], empty_reason: "Not run yet." } : undefined);
  await page.goto(`/dashboard/websites/${SITE}/intelligence`);
  await page.getByRole("tab", { name: "Technical" }).click();
  await shot(page, "intelligence", () => page.getByTestId("tech-checks").waitFor(), { h: 960 });
});
test("history", async ({ page }) => {
  await route(page, (p) => p.endsWith("/history/overview") ? histOverview : p.endsWith("/history/snapshots") ? { items: [H_LAST, H_BASE], total: 2 } : p.endsWith("/history/compare") ? histCompare
    : p.endsWith("/history/search-comparison") ? { available: false, reason: "Not enough Search Console history yet.", rows: [], freshness: { latest_data_date: null, last_synced_at: null, note: "" } }
    : p.endsWith("/history/series") ? { metric: "health", label: "RankPilot health score", family: "internal_score", source: "RankPilot crawl", start: iso(45), end: iso(1), available: true, points: [{ date: "2026-10-10", value: 62 }, { date: "2026-10-24", value: 74 }, { date: "2026-11-07", value: 86 }, { date: "2026-11-23", value: 91 }], note: "" }
    : p.endsWith("/history/timeline") ? { items: [{ id: "e1", category: "snapshot", event_type: "baseline_established", title: "Baseline established: where this project started", occurred_at: iso(45), detail: {} }], page: 1, page_size: 20, total: 1, pages: 1 } : undefined);
  await page.goto(`/dashboard/websites/${SITE}/history`);
  await shot(page, "history", () => page.getByText(/Overall SEO health score/).first().waitFor(), { h: 960 });
});

test("keywords", async ({ page }) => {
  await route(page, () => undefined);
  await page.goto(`/dashboard/websites/${SITE}/keywords`);
  await page.getByRole("button", { name: "Opportunities & Mapping" }).or(page.getByRole("tab", { name: "Opportunities & Mapping" })).first().click();
  await shot(page, "keywords", () => page.getByText("Opportunities & Keyword-to-Page Mapping").waitFor(), { h: 900 });
});
