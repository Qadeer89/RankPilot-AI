import type { Page, Route } from "@playwright/test";

export const ORG = "00000000-0000-4000-8000-000000000001";
export const SITE = "00000000-0000-4000-8000-000000000002";
const base = `/api/v1/organizations/${ORG}/websites/${SITE}`;

export const COUNTRIES = [
  { code: "US", name: "United States" },
  { code: "GB", name: "United Kingdom" },
  { code: "PK", name: "Pakistan" },
  { code: "CA", name: "Canada" },
  { code: "AU", name: "Australia" },
];

type Json = Record<string, unknown>;

export interface FakeOptions {
  target_country?: string | null;
  additional_target_countries?: string[];
  target_languages_by_country?: Record<string, string>;
  // what the verification crawl finds once the change is applied
  recrawlOutcome?: "validated" | "mismatch" | "failed";
  settingsError?: string;
  recommendationsToGenerate?: Json[];
  cmsConnected?: boolean;
  discoveryResponse?: Json;
  analyzeResponse?: Json;
  timeline?: Json;
}

export function recommendation(over: Json = {}): Json {
  return {
    id: "rec-1",
    recommendation_type: "improve_existing_page",
    title: 'Strengthen the page ranking for "knee pain"',
    page_id: "page-1",
    proposed_url: null,
    opportunity_id: null,
    target_country: "PK",
    keyword: "knee pain",
    data_source: "google_search_console",
    problem: "Second page of results.",
    recommended_action: "Rewrite the title.",
    expected_benefit: "Could improve visibility. Not guaranteed.",
    priority: "high",
    difficulty: "medium",
    automation_available: true,
    requires_approval: true,
    validation_method: "Compare Search Console before and after.",
    evidence_json: { impressions: 150 },
    status: "open",
    updated_at: new Date().toISOString(),
    lifecycle: {},
    ...over,
  };
}

/**
 * A small stateful stand-in for the RankPilot API. It records every request
 * (`calls`) so tests can assert exactly what the UI sent.
 */
export class FakeApi {
  calls: { method: string; path: string; body: Json | null }[] = [];
  website: Json;
  recs: Json[] = [];
  private task: Json | null = null;
  private change: Json | null = null;
  private recrawl: Json | null = null;
  private getsSinceQueued = 0;
  private opts: FakeOptions;

  constructor(opts: FakeOptions = {}) {
    this.opts = { recrawlOutcome: "validated", cmsConnected: true, ...opts };
    this.website = {
      id: SITE, organization_id: ORG, canonical_url: "https://clinic.example/", hostname: "clinic.example",
      display_name: "Example Clinic", verification_status: "verified", platform: "wordpress", crawl_budget: 50,
      status: "active", automation_policy: {}, automation_mode: "copilot", crawl_frequency_hours: 24,
      ai_daily_budget_usd_override: null, search_console_site_url: "sc-domain:clinic.example", ga4_property_id: "properties/1",
      target_country: opts.target_country === undefined ? "PK" : opts.target_country,
      additional_target_countries: opts.additional_target_countries ?? ["GB"],
      target_language: "en", target_city: null, target_languages_by_country: opts.target_languages_by_country ?? {},
    };
  }

  requests(method: string, pathPart: string) {
    return this.calls.filter((c) => c.method === method && c.path.includes(pathPart));
  }

  private lifecycle(rec: Json): Json {
    if (!this.opts.cmsConnected) {
      return { lifecycle_status: rec.status === "open" ? "pending" : rec.status === "done" ? "applied" : "approved", supported: false,
        unsupported_reason: "No CMS is connected. Connect one in Integrations to apply this from RankPilot.",
        applied_manually: rec.status === "done", tasks: [] };
    }
    if (rec.recommendation_type !== "improve_existing_page") {
      return { lifecycle_status: rec.status === "open" ? "pending" : rec.status === "done" ? "applied" : "approved", supported: false,
        unsupported_reason: "RankPilot has no automated change for this kind of recommendation. Apply it by hand, then mark it done.",
        applied_manually: rec.status === "done", tasks: [] };
    }
    const info: Json = { lifecycle_status: rec.status === "open" ? "pending" : "approved", supported: true, unsupported_reason: null, tasks: [] };
    if (this.task) {
      const approved = this.task.approval_status === "approved";
      let state = "in_progress";
      if (this.change) state = (this.recrawl as Json | null)?.status === "validated" ? "validated" : "validation_pending";
      info.lifecycle_status = state;
      info.tasks = [{
        task_id: "task-1", operation: "set_title", target_url: "https://clinic.example/knee",
        proposed_value: "Knee Pain Treatment | Example Clinic", summary: "Better title", task_status: approved ? "approved" : "pending",
        approval_status: this.task.approval_status, state, change_record_id: this.change ? "change-1" : null,
        before_value: this.change ? "Old title" : null, applied_value: this.change ? "Knee Pain Treatment | Example Clinic" : null,
        connector: this.change ? "wordpress" : null, recrawl: this.recrawl,
      }];
    }
    return info;
  }

  private recsOut() {
    return this.recs.map((r) => ({ ...r, lifecycle: this.lifecycle(r) }));
  }

  /** The verification crawl "finishes" the next time the page asks for recommendations. */
  private settleRecrawl() {
    if (this.recrawl && ["queued", "running"].includes(this.recrawl.status as string)) {
      // the crawl is still in flight for the first look (the refresh that
      // follows the click), and finishes by the next one (the page's poll)
      this.getsSinceQueued += 1;
      if (this.getsSinceQueued < 2) return;
      const outcome = this.opts.recrawlOutcome;
      this.recrawl =
        outcome === "validated"
          ? { status: "validated", url: "https://clinic.example/knee", expected: "Knee Pain Treatment | Example Clinic", found: "Knee Pain Treatment | Example Clinic" }
          : outcome === "mismatch"
            ? { status: "mismatch", url: "https://clinic.example/knee", expected: "Knee Pain Treatment | Example Clinic", found: "Old title" }
            : { status: "failed", error: "The page returned HTTP 500." };
    }
  }

  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({
      status,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" },
      body: JSON.stringify(body),
    });
  }

  private async handle(route: Route) {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    if (method === "OPTIONS") return this.json(route, {}, 204);
    let body: Json | null = null;
    try { body = req.postDataJSON() as Json | null; } catch { body = null; }
    this.calls.push({ method, path: path + url.search, body });
    const is = (m: string, re: RegExp) => method === m && re.test(path);

    if (is("GET", /\/api\/v1\/me$/)) {
      return this.json(route, { user: { id: "u1", email: "owner@example.com", is_platform_admin: false },
        organizations: [{ id: ORG, name: "Clinic Org", slug: "clinic", role: "owner" }] });
    }
    if (is("GET", /\/reference\/countries$/)) return this.json(route, COUNTRIES);
    if (is("GET", new RegExp(`${base}$`))) return this.json(route, this.website);
    if (is("PATCH", new RegExp(`${base}/settings$`))) {
      if (this.opts.settingsError) return this.json(route, { detail: this.opts.settingsError }, 400);
      const next = { ...this.website };
      for (const [k, v] of Object.entries(body ?? {})) {
        if (k === "target_country") next[k] = v === "" ? null : v;
        else next[k] = v;
      }
      this.website = next;
      return this.json(route, this.website);
    }
    if (is("GET", new RegExp(`${base}/search-performance$`))) {
      return this.json(route, { source: "google_search_console", freshness_note: "Search Console data lags 2-3 days.", rows: [
        { query: "knee pain", date: "2026-11-10", clicks: 3, impressions: 120, ctr: 0.025, average_position: 14, country: "PK", device: "MOBILE", page_id: "page-1" }] });
    }
    if (is("GET", new RegExp(`${base}/search-performance/intelligence$`))) {
      return this.json(route, { freshness_note: "", country: url.searchParams.get("country"), declining_pages: [],
        ranking_improvement_opportunities: [], keyword_cannibalization: [], new_queries: [] });
    }
    if (is("GET", new RegExp(`${base}/keyword-ideas$`))) return this.json(route, []);
    if (is("POST", new RegExp(`${base}/keyword-discovery/run$`))) {
      return this.json(route, this.opts.discoveryResponse ?? { ideas: [], freshness_note: "", ai_status: "ok", ai_message: null });
    }
    if (is("GET", new RegExp(`${base}/competitors$`))) return this.json(route, [{ id: "comp-1", domain: "rival.example", last_analyzed_at: null, created_at: "2026-11-01T00:00:00Z" }]);
    if (is("POST", new RegExp(`${base}/competitors/comp-1/analyze$`))) {
      return this.json(route, this.opts.analyzeResponse ?? { ideas: [], pages_fetched: 3, pages_failed: 0, ai_status: "ok", ai_message: null });
    }
    if (is("GET", new RegExp(`${base}/competitors/comp-1/pages$`))) return this.json(route, []);
    if (is("GET", new RegExp(`${base}/ai-usage$`))) return this.json(route, { days: 30, by_agent_type: [], total_estimated_cost_usd: 0, note: "" });
    if (is("GET", new RegExp(`${base}/performance-timeline$`))) {
      return this.json(route, this.opts.timeline ?? { window_days: 28, caveat: "Correlation, not proof.", entries: [] });
    }

    // growth recommendations
    if (is("GET", new RegExp(`${base}/growth-recommendations$`))) { this.settleRecrawl(); return this.json(route, this.recsOut()); }
    if (is("POST", new RegExp(`${base}/growth-recommendations/generate`))) {
      this.recs = (this.opts.recommendationsToGenerate ?? []) as Json[];
      return this.json(route, this.recsOut());
    }
    const recPatch = path.match(new RegExp(`${base}/growth-recommendations/([^/]+)$`));
    if (method === "PATCH" && recPatch) {
      const rec = this.recs.find((r) => r.id === recPatch[1]) as Json;
      rec.status = (body as Json).status;
      return this.json(route, { ...rec, lifecycle: this.lifecycle(rec) });
    }
    if (is("POST", new RegExp(`${base}/growth-recommendations/[^/]+/send-to-execution$`))) {
      const rec = this.recs[0];
      rec.opportunity_id = "opp-1";
      return this.json(route, { ...rec, lifecycle: this.lifecycle(rec) });
    }
    if (is("POST", new RegExp(`${base}/opportunities/opp-1/proposals$`))) return this.json(route, { opportunity_id: "opp-1", summary: "Better title", proposed_actions: [] });
    if (is("POST", new RegExp(`${base}/opportunities/opp-1/tasks$`))) {
      this.task = { approval_status: "pending" };
      return this.json(route, [{ id: "task-1" }]);
    }
    if (is("POST", new RegExp(`${base}/tasks/task-1/dry-run$`))) {
      return this.json(route, { operation: "set_title", target_url: "https://clinic.example/knee", before_value: "Old title", proposed_value: "Knee Pain Treatment | Example Clinic", changed: true });
    }
    if (is("POST", new RegExp(`${base}/tasks/task-1/approve$`))) { (this.task as Json).approval_status = "approved"; return this.json(route, { id: "task-1" }); }
    if (is("POST", new RegExp(`${base}/tasks/task-1/execute$`))) {
      this.change = { id: "change-1" };
      this.getsSinceQueued = 0;
      this.recrawl = { status: "queued", url: "https://clinic.example/knee" };
      return this.json(route, { id: "change-1", validation_status: "passed" });
    }
    if (is("POST", new RegExp(`${base}/growth-recommendations/[^/]+/recrawl$`))) {
      this.getsSinceQueued = 0;
      this.recrawl = { status: "queued", url: "https://clinic.example/knee" };
      return this.json(route, { ...this.recs[0], lifecycle: this.lifecycle(this.recs[0]) });
    }
    if (is("POST", new RegExp(`${base}/growth-recommendations/[^/]+/verify-live$`))) {
      return this.json(route, { checked_at: new Date().toISOString(), matched: true, checks: [] });
    }
    return this.json(route, { detail: `fake api: unhandled ${method} ${path}` }, 404);
  }
}
