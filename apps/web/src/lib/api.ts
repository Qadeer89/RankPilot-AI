const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string
  ) {
    super(message);
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    let code: string | undefined;
    try {
      const body = await response.json();
      const raw = body.detail;
      if (typeof raw === "string") {
        detail = raw;
      } else if (raw && typeof raw === "object" && !Array.isArray(raw) && typeof raw.message === "string") {
        // Structured errors: { code, message } (billing endpoints).
        detail = raw.message;
        code = typeof raw.code === "string" ? raw.code : undefined;
      } else if (Array.isArray(raw)) {
        // FastAPI validation errors.
        detail = raw.map((e) => (e && typeof e === "object" && "msg" in e ? String(e.msg) : String(e))).join("; ");
      }
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, detail, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface MeResponse {
  user: { id: string; email: string; is_platform_admin: boolean; is_super_admin: boolean; email_verified: boolean };
  organizations: OrganizationSummary[];
}

export interface Website {
  id: string;
  organization_id: string;
  canonical_url: string;
  hostname: string;
  display_name: string;
  verification_status: string;
  platform: string;
  crawl_budget: number;
  status: string;
  automation_policy: {
    auto_execute_risk_tier_1?: boolean;
    auto_execute_categories?: Record<string, boolean>;
    notify_on_regression?: boolean;
    notify_on_auto_pipeline_summary?: boolean;
  };
  automation_mode: "audit" | "copilot" | "autopilot";
  crawl_frequency_hours: number;
  ai_daily_budget_usd_override: number | null;
  search_console_site_url: string | null;
  ga4_property_id: string | null;
  target_country: string | null;
  additional_target_countries: string[];
  target_language: string | null;
  target_city: string | null;
  target_languages_by_country: Record<string, string>;
}

export interface CrawlJob {
  id: string;
  website_id: string;
  trigger: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  pages_requested: number;
  pages_fetched: number;
  error_summary: string | null;
}

export interface SiteHealthScore {
  id: string;
  website_id: string;
  crawl_job_id: string;
  overall_score: number | null;
  technical_score: number | null;
  on_page_score: number | null;
  content_score: number | null;
  performance_score: number | null;
  critical_count: number;
  warning_count: number;
  info_count: number;
  passed_count: number;
  created_at: string;
}

export interface Page {
  id: string;
  website_id: string;
  canonical_url: string;
  normalized_url: string;
  last_status_code: number | null;
  indexability_state: string;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SEOFinding {
  id: string;
  website_id: string;
  page_id: string | null;
  rule_code: string;
  severity: string;
  confidence: number;
  evidence_json: Record<string, unknown>;
  first_detected_at: string;
  last_detected_at: string;
  status: string;
}

export interface Opportunity {
  id: string;
  website_id: string;
  page_id: string | null;
  category: string;
  title: string;
  rationale: string;
  impact_estimate: number;
  confidence: number;
  effort_estimate: number;
  risk_tier: number;
  score: number;
  status: string;
}

export interface OpportunityProposal {
  opportunity_id: string;
  summary: string;
  evidence: { page_url: string; finding_code: string }[];
  proposed_actions: { operation: string; target_url: string; value: string }[];
  risk_tier: number;
  confidence: number;
  requires_approval: boolean;
  validation_plan: string[];
}

export interface SEOTask {
  id: string;
  website_id: string;
  opportunity_id: string | null;
  task_type: string;
  status: string;
  risk_tier: number;
  proposed_change_json: Record<string, unknown>;
  approval_status: string;
}

export interface ChangeRecord {
  id: string;
  website_id: string;
  page_id: string | null;
  seo_task_id: string;
  connector_type: string;
  before_state_json: Record<string, unknown>;
  after_state_json: Record<string, unknown>;
  actor_type: string;
  executed_at: string;
  validation_status: string;
}

export interface RollbackRecord {
  id: string;
  change_record_id: string;
  rollback_method: string;
  status: string;
  completed_at: string | null;
  result_json: Record<string, unknown>;
}

export interface WebsiteConnection {
  id: string;
  website_id: string;
  connector_type: string;
  status: string;
  config_json: Record<string, unknown>;
  last_verified_at: string | null;
}

export interface SearchPerformanceRow {
  query: string;
  date: string;
  clicks: number;
  impressions: number;
  ctr: number;
  average_position: number;
  country: string | null;
  device: string | null;
  page_id: string | null;
}

export interface SearchPerformance {
  source: string;
  freshness_note: string;
  rows: SearchPerformanceRow[];
}

export interface Report {
  id: string;
  website_id: string;
  period_start: string;
  period_end: string;
  report_type: string;
  content_json: Record<string, unknown>;
}

export interface VerificationInstructions {
  website_id: string;
  method: string;
  token: string;
  instructions: string;
}

export interface VerificationResult {
  website_id: string;
  verification_status: string;
  verified: boolean;
  detail: string;
}

export function register(email: string, password: string, organizationName: string) {
  return request<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, organization_name: organizationName }),
  });
}

export function login(email: string, password: string) {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export interface MessageResponse {
  message: string;
}

export function forgotPassword(email: string) {
  return request<MessageResponse>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function resetPassword(token: string, newPassword: string) {
  return request<MessageResponse>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export function verifyEmail(token: string) {
  return request<MessageResponse>("/auth/verify-email", { method: "POST", body: JSON.stringify({ token }) });
}

export function sendVerificationEmail(token: string) {
  return request<MessageResponse>("/auth/send-verification-email", { method: "POST", headers: authHeaders(token) });
}

export function getMe(token: string) {
  return request<MeResponse>("/me", { headers: authHeaders(token) });
}

export function listWebsites(token: string, organizationId: string) {
  return request<Website[]>(`/organizations/${organizationId}/websites`, {
    headers: authHeaders(token),
  });
}

export function deleteWebsite(token: string, organizationId: string, websiteId: string) {
  return request<void>(`/organizations/${organizationId}/websites/${websiteId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export function registerWebsite(
  token: string,
  organizationId: string,
  url: string,
  displayName: string
) {
  return request<Website>(`/organizations/${organizationId}/websites`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ url, display_name: displayName }),
  });
}

export function startVerification(token: string, organizationId: string, websiteId: string) {
  return request<VerificationInstructions>(
    `/organizations/${organizationId}/websites/${websiteId}/verify/instructions`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function confirmVerification(
  token: string,
  organizationId: string,
  websiteId: string,
  verificationToken: string
) {
  return request<VerificationResult>(
    `/organizations/${organizationId}/websites/${websiteId}/verify`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ token: verificationToken }),
    }
  );
}

export function getWebsite(token: string, organizationId: string, websiteId: string) {
  return request<Website>(`/organizations/${organizationId}/websites/${websiteId}`, {
    headers: authHeaders(token),
  });
}

export function updateWebsiteSettings(
  token: string,
  organizationId: string,
  websiteId: string,
  payload: {
    auto_execute_risk_tier_1?: boolean;
    crawl_budget?: number;
    display_name?: string;
    automation_mode?: "audit" | "copilot" | "autopilot";
    auto_execute_categories?: Record<string, boolean>;
    crawl_frequency_hours?: number;
    ai_daily_budget_usd_override?: number;
    target_country?: string;
    additional_target_countries?: string[];
    target_language?: string;
    target_city?: string;
    target_languages_by_country?: Record<string, string>;
    notify_on_regression?: boolean;
    notify_on_auto_pipeline_summary?: boolean;
  }
) {
  return request<Website>(`/organizations/${organizationId}/websites/${websiteId}/settings`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export function pauseWebsite(token: string, organizationId: string, websiteId: string) {
  return request<Website>(`/organizations/${organizationId}/websites/${websiteId}/pause`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

// --- Crawls, pages, findings ---

export function triggerCrawl(token: string, organizationId: string, websiteId: string) {
  return request<CrawlJob>(`/organizations/${organizationId}/websites/${websiteId}/crawls`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export function listCrawls(token: string, organizationId: string, websiteId: string) {
  return request<CrawlJob[]>(`/organizations/${organizationId}/websites/${websiteId}/crawls`, {
    headers: authHeaders(token),
  });
}

export function listPages(token: string, organizationId: string, websiteId: string) {
  return request<Page[]>(`/organizations/${organizationId}/websites/${websiteId}/pages`, {
    headers: authHeaders(token),
  });
}

export function listFindings(token: string, organizationId: string, websiteId: string) {
  return request<SEOFinding[]>(`/organizations/${organizationId}/websites/${websiteId}/findings`, {
    headers: authHeaders(token),
  });
}

export function listHealthScores(token: string, organizationId: string, websiteId: string) {
  return request<SiteHealthScore[]>(`/organizations/${organizationId}/websites/${websiteId}/health-score`, {
    headers: authHeaders(token),
  });
}

export interface WebsiteOverview {
  pages_discovered: number;
  pages_indexed: number | null;
  pages_inspected?: number | null;
  indexing_last_checked_at?: string | null;
  pending_approvals: number;
  latest_health_score: SiteHealthScore | null;
}

export function getWebsiteOverview(token: string, organizationId: string, websiteId: string) {
  return request<WebsiteOverview>(`/organizations/${organizationId}/websites/${websiteId}/overview`, {
    headers: authHeaders(token),
  });
}

export interface PageSnapshotSummary {
  fetched_at: string;
  status_code: number | null;
  redirect_count: number;
  title: string | null;
  meta_description: string | null;
  canonical_url: string | null;
  robots_directives: string[];
  heading_sequence_json: number[];
  structured_data_json: Record<string, unknown>[];
  word_count: number;
  viewport_content: string | null;
  rel_next_url: string | null;
  rel_prev_url: string | null;
}

export interface PageImageSummary {
  image_src: string | null;
  alt_text: string | null;
  has_alt: boolean;
  is_decorative: boolean;
  has_dimensions: boolean;
  image_status: string;
}

export interface PageExternalLinkSummary {
  url: string;
  is_nofollow: boolean;
  is_sponsored: boolean;
  is_ugc: boolean;
  link_status: string;
}

export interface PerformanceMetricSummary {
  strategy: string;
  lab_performance_score: number | null;
  lab_lcp_ms: number | null;
  lab_cls: number | null;
  lab_tbt_ms: number | null;
  field_lcp_ms: number | null;
  field_cls: number | null;
  field_inp_ms: number | null;
  opportunities_json: Record<string, unknown>[];
}

export interface PageIndexingStatusSummary {
  verdict: string;
  coverage_state: string | null;
  indexing_state: string | null;
  last_crawl_time: string | null;
  google_canonical_url: string | null;
  user_canonical_url: string | null;
  mobile_usability_verdict: string | null;
  mobile_usability_issues_json: Record<string, unknown>[];
}

export interface PageReport {
  page: Page;
  latest_snapshot: PageSnapshotSummary | null;
  images: PageImageSummary[];
  external_links: PageExternalLinkSummary[];
  performance: PerformanceMetricSummary | null;
  indexing_status: PageIndexingStatusSummary | null;
  findings: SEOFinding[];
  change_history: ChangeRecord[];
}

export function getPageReport(token: string, organizationId: string, websiteId: string, pageId: string) {
  return request<PageReport>(
    `/organizations/${organizationId}/websites/${websiteId}/pages/${pageId}/report`,
    { headers: authHeaders(token) }
  );
}

export function listChangeRecords(
  token: string,
  organizationId: string,
  websiteId: string,
  pageId?: string
) {
  const query = pageId ? `?page_id=${pageId}` : "";
  return request<ChangeRecord[]>(
    `/organizations/${organizationId}/websites/${websiteId}/change-records${query}`,
    { headers: authHeaders(token) }
  );
}

// --- Opportunities and AI proposals ---

export function listOpportunities(token: string, organizationId: string, websiteId: string) {
  return request<Opportunity[]>(
    `/organizations/${organizationId}/websites/${websiteId}/opportunities`,
    { headers: authHeaders(token) }
  );
}

export function createProposal(
  token: string,
  organizationId: string,
  websiteId: string,
  opportunityId: string
) {
  return request<OpportunityProposal>(
    `/organizations/${organizationId}/websites/${websiteId}/opportunities/${opportunityId}/proposals`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function createTasks(
  token: string,
  organizationId: string,
  websiteId: string,
  opportunityId: string,
  proposal: OpportunityProposal
) {
  return request<SEOTask[]>(
    `/organizations/${organizationId}/websites/${websiteId}/opportunities/${opportunityId}/tasks`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify(proposal) }
  );
}

// --- Tasks, approvals, execution ---

export function listTasks(token: string, organizationId: string, websiteId: string) {
  return request<SEOTask[]>(`/organizations/${organizationId}/websites/${websiteId}/tasks`, {
    headers: authHeaders(token),
  });
}

export function approveTask(
  token: string,
  organizationId: string,
  websiteId: string,
  taskId: string,
  reason?: string
) {
  return request<SEOTask>(
    `/organizations/${organizationId}/websites/${websiteId}/tasks/${taskId}/approve`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify({ reason: reason ?? null }) }
  );
}

export function rejectTask(
  token: string,
  organizationId: string,
  websiteId: string,
  taskId: string,
  reason?: string
) {
  return request<SEOTask>(
    `/organizations/${organizationId}/websites/${websiteId}/tasks/${taskId}/reject`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify({ reason: reason ?? null }) }
  );
}

export function cancelTask(
  token: string,
  organizationId: string,
  websiteId: string,
  taskId: string,
  reason?: string
) {
  return request<SEOTask>(
    `/organizations/${organizationId}/websites/${websiteId}/tasks/${taskId}/cancel`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify({ reason: reason ?? null }) }
  );
}

export function executeTask(token: string, organizationId: string, websiteId: string, taskId: string) {
  return request<ChangeRecord>(
    `/organizations/${organizationId}/websites/${websiteId}/tasks/${taskId}/execute`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function getChangeRecord(
  token: string,
  organizationId: string,
  websiteId: string,
  changeId: string
) {
  return request<ChangeRecord>(
    `/organizations/${organizationId}/websites/${websiteId}/change-records/${changeId}`,
    { headers: authHeaders(token) }
  );
}

export function rollbackChange(
  token: string,
  organizationId: string,
  websiteId: string,
  changeId: string
) {
  return request<RollbackRecord>(
    `/organizations/${organizationId}/websites/${websiteId}/change-records/${changeId}/rollback`,
    { method: "POST", headers: authHeaders(token) }
  );
}

// --- WordPress connector ---

export function connectWordPress(
  token: string,
  organizationId: string,
  websiteId: string,
  username: string,
  applicationPassword: string
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/wordpress`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ username, application_password: applicationPassword }),
    }
  );
}

export function disconnectWordPress(token: string, organizationId: string, websiteId: string) {
  return request<void>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/wordpress`,
    { method: "DELETE", headers: authHeaders(token) }
  );
}

export function listConnections(token: string, organizationId: string, websiteId: string) {
  return request<WebsiteConnection[]>(
    `/organizations/${organizationId}/websites/${websiteId}/connections`,
    { headers: authHeaders(token) }
  );
}

// --- Shopify connector ---

export function connectShopify(
  token: string,
  organizationId: string,
  websiteId: string,
  shopDomain: string,
  accessToken: string
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/shopify`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ shop_domain: shopDomain, access_token: accessToken }),
    }
  );
}

export function disconnectShopify(token: string, organizationId: string, websiteId: string) {
  return request<void>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/shopify`,
    { method: "DELETE", headers: authHeaders(token) }
  );
}

// --- Webflow connector ---

export function connectWebflow(
  token: string,
  organizationId: string,
  websiteId: string,
  siteId: string,
  accessToken: string
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/webflow`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ site_id: siteId, access_token: accessToken }),
    }
  );
}

export function disconnectWebflow(token: string, organizationId: string, websiteId: string) {
  return request<void>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/webflow`,
    { method: "DELETE", headers: authHeaders(token) }
  );
}

// --- GitHub connector (custom-code sites) ---

export function connectGitHub(
  token: string,
  organizationId: string,
  websiteId: string,
  owner: string,
  repo: string,
  baseBranch: string,
  accessToken: string
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/github`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ owner, repo, base_branch: baseBranch, access_token: accessToken }),
    }
  );
}

export function disconnectGitHub(token: string, organizationId: string, websiteId: string) {
  return request<void>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/github`,
    { method: "DELETE", headers: authHeaders(token) }
  );
}

export function setGitHubAutoMerge(
  token: string,
  organizationId: string,
  websiteId: string,
  autoMergeOnCiSuccess: boolean
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/github/settings`,
    {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify({ auto_merge_on_ci_success: autoMergeOnCiSuccess }),
    }
  );
}

// --- Sanity CMS connector ---

export function connectSanity(
  token: string,
  organizationId: string,
  websiteId: string,
  projectId: string,
  dataset: string,
  sanityToken: string
) {
  return request<WebsiteConnection>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/sanity`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ project_id: projectId, dataset, token: sanityToken }),
    }
  );
}

export function disconnectSanity(token: string, organizationId: string, websiteId: string) {
  return request<void>(
    `/organizations/${organizationId}/websites/${websiteId}/connections/sanity`,
    { method: "DELETE", headers: authHeaders(token) }
  );
}

// --- Google Search Console ---

export function startGoogleConnect(token: string, organizationId: string) {
  return request<{ authorization_url: string }>(
    `/organizations/${organizationId}/integrations/google/search-console/connect`,
    { headers: authHeaders(token) }
  );
}

export function disconnectGoogle(token: string, organizationId: string) {
  return request<void>(
    `/organizations/${organizationId}/integrations/google/search-console/disconnect`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function getSearchProperties(token: string, organizationId: string, websiteId: string) {
  return request<{ site_urls: string[] }>(
    `/organizations/${organizationId}/websites/${websiteId}/search-properties`,
    { headers: authHeaders(token) }
  );
}

export function selectSearchProperty(
  token: string,
  organizationId: string,
  websiteId: string,
  siteUrl: string
) {
  return request<Website>(
    `/organizations/${organizationId}/websites/${websiteId}/search-console/select`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify({ site_url: siteUrl }) }
  );
}

export function syncSearchConsole(token: string, organizationId: string, websiteId: string) {
  return request<{ rows_synced: number }>(
    `/organizations/${organizationId}/websites/${websiteId}/search-console/sync`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function getSearchPerformance(token: string, organizationId: string, websiteId: string) {
  return request<SearchPerformance>(
    `/organizations/${organizationId}/websites/${websiteId}/search-performance`,
    { headers: authHeaders(token) }
  );
}

// --- SEO Growth Engine: search intelligence, keyword ideas, competitors ---

export interface WindowStats {
  clicks: number;
  impressions: number;
  average_position: number;
}

export interface PageTrendSignal {
  page_id: string;
  signals: string[];
  prior: WindowStats;
  recent: WindowStats;
}

export interface RankingOpportunity {
  query: string;
  page_id: string | null;
  average_position: number;
  impressions: number;
}

export interface CannibalizationCandidate {
  query: string;
  pages: { page_id: string | null; impressions: number; average_position: number }[];
}

export interface NewQuery {
  query: string;
  page_id: string | null;
  impressions: number;
  clicks: number;
  average_position: number;
  country: string | null;
}

export interface SearchPerformanceIntelligence {
  freshness_note: string;
  country: string | null;
  declining_pages: PageTrendSignal[];
  ranking_improvement_opportunities: RankingOpportunity[];
  keyword_cannibalization: CannibalizationCandidate[];
  new_queries: NewQuery[];
}

export function getSearchPerformanceIntelligence(
  token: string,
  organizationId: string,
  websiteId: string,
  country?: string
) {
  const query = country ? `?country=${encodeURIComponent(country)}` : "";
  return request<SearchPerformanceIntelligence>(
    `/organizations/${organizationId}/websites/${websiteId}/search-performance/intelligence${query}`,
    { headers: authHeaders(token) }
  );
}

export type SearchIntent = "informational" | "commercial" | "transactional" | "navigational" | "local";
export type KeywordIdeaSource = "seed" | "ai_generated" | "public_suggestion" | "competitor_gap";
export type KeywordDataClassification =
  | "verified_first_party"
  | "verified_external_source"
  | "public_search_suggestion"
  | "ai_generated_idea"
  | "ai_estimated_relevance"
  | "unavailable";
export type KeywordIdeaStatus = "new" | "dismissed" | "actioned";

export interface KeywordIdea {
  id: string;
  keyword: string;
  search_intent: SearchIntent;
  source: KeywordIdeaSource;
  data_classification: KeywordDataClassification;
  country: string | null;
  language: string | null;
  relevance: number;
  confidence: number;
  recommended_content_type: string | null;
  target_page_id: string | null;
  proposed_title: string | null;
  rationale: string;
  cluster_key: string | null;
  status: KeywordIdeaStatus;
  brand_search?: boolean;
  created_at: string;
}

export type AiStatus = "ok" | "skipped_no_input" | "budget_blocked" | "unavailable" | "invalid_response" | "input_too_large";

export interface KeywordDiscoveryRun {
  ideas: KeywordIdea[];
  freshness_note: string;
  ai_status: AiStatus;
  ai_message: string | null;
}

export interface CompetitorAnalysisResult {
  ideas: KeywordIdea[];
  pages_fetched: number;
  pages_failed: number;
  ai_status: AiStatus;
  ai_message: string | null;
}

export function runKeywordDiscovery(
  token: string,
  organizationId: string,
  websiteId: string,
  payload: { country?: string | null; max_ideas?: number }
) {
  return request<KeywordDiscoveryRun>(
    `/organizations/${organizationId}/websites/${websiteId}/keyword-discovery/run`,
    { method: "POST", headers: authHeaders(token), body: JSON.stringify(payload) }
  );
}

export function listKeywordIdeas(
  token: string,
  organizationId: string,
  websiteId: string,
  filters?: { country?: string; source?: KeywordIdeaSource; status_filter?: KeywordIdeaStatus }
) {
  const params = new URLSearchParams();
  if (filters?.country) params.set("country", filters.country);
  if (filters?.source) params.set("source", filters.source);
  if (filters?.status_filter) params.set("status_filter", filters.status_filter);
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<KeywordIdea[]>(
    `/organizations/${organizationId}/websites/${websiteId}/keyword-ideas${query}`,
    { headers: authHeaders(token) }
  );
}

export function updateKeywordIdeaStatus(
  token: string,
  organizationId: string,
  websiteId: string,
  ideaId: string,
  status: KeywordIdeaStatus
) {
  return request<KeywordIdea>(
    `/organizations/${organizationId}/websites/${websiteId}/keyword-ideas/${ideaId}`,
    { method: "PATCH", headers: authHeaders(token), body: JSON.stringify({ status }) }
  );
}

export interface CompetitorDomain {
  id: string;
  domain: string;
  last_analyzed_at: string | null;
  created_at: string;
}

export interface CompetitorPageSnapshot {
  id: string;
  url: string;
  title: string | null;
  meta_description: string | null;
  word_count: number;
  has_structured_data: boolean;
  fetch_error: string | null;
  fetched_at: string;
}

export function listCompetitors(token: string, organizationId: string, websiteId: string) {
  return request<CompetitorDomain[]>(`/organizations/${organizationId}/websites/${websiteId}/competitors`, {
    headers: authHeaders(token),
  });
}

export function addCompetitor(token: string, organizationId: string, websiteId: string, domain: string) {
  return request<CompetitorDomain>(`/organizations/${organizationId}/websites/${websiteId}/competitors`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ domain }),
  });
}

export function analyzeCompetitor(token: string, organizationId: string, websiteId: string, competitorId: string) {
  return request<CompetitorAnalysisResult>(
    `/organizations/${organizationId}/websites/${websiteId}/competitors/${competitorId}/analyze`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function listCompetitorPages(token: string, organizationId: string, websiteId: string, competitorId: string) {
  return request<CompetitorPageSnapshot[]>(
    `/organizations/${organizationId}/websites/${websiteId}/competitors/${competitorId}/pages`,
    { headers: authHeaders(token) }
  );
}

export function deleteCompetitor(token: string, organizationId: string, websiteId: string, competitorId: string) {
  return request<void>(`/organizations/${organizationId}/websites/${websiteId}/competitors/${competitorId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

// --- Reports ---

export function listReports(token: string, organizationId: string, websiteId: string) {
  return request<Report[]>(`/organizations/${organizationId}/websites/${websiteId}/reports`, {
    headers: authHeaders(token),
  });
}

// --- Google Analytics (GA4) ---

export interface Ga4Property {
  property_id: string;
  display_name: string;
}

export interface Ga4MetricsRow {
  date: string;
  sessions: number;
  total_users: number;
  conversions: number;
}

export interface Ga4Metrics {
  source: string;
  freshness_note: string;
  rows: Ga4MetricsRow[];
}

export function startGa4Connect(token: string, organizationId: string) {
  return request<{ authorization_url: string }>(
    `/organizations/${organizationId}/integrations/google/analytics/connect`,
    { headers: authHeaders(token) }
  );
}

export function disconnectGa4(token: string, organizationId: string) {
  return request<void>(`/organizations/${organizationId}/integrations/google/analytics/disconnect`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export function getGa4Properties(token: string, organizationId: string, websiteId: string) {
  return request<{ properties: Ga4Property[] }>(
    `/organizations/${organizationId}/websites/${websiteId}/ga4-properties`,
    { headers: authHeaders(token) }
  );
}

export function selectGa4Property(
  token: string,
  organizationId: string,
  websiteId: string,
  propertyId: string
) {
  return request<Website>(`/organizations/${organizationId}/websites/${websiteId}/ga4/select`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ property_id: propertyId }),
  });
}

export function syncGa4(token: string, organizationId: string, websiteId: string) {
  return request<{ rows_synced: number }>(
    `/organizations/${organizationId}/websites/${websiteId}/ga4/sync`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function getGa4Metrics(token: string, organizationId: string, websiteId: string) {
  return request<Ga4Metrics>(`/organizations/${organizationId}/websites/${websiteId}/ga4-metrics`, {
    headers: authHeaders(token),
  });
}

// --- AI agents (QA Assistant, Strategy Assistant, Internal Linking Analyst) ---

export interface QaSummary {
  summary: string;
  validation_status: string;
}

export interface StrategySummary {
  narrative: string;
  focus_areas: string[];
}

export interface LinkSuggestion {
  source_url: string;
  anchor_text: string;
  rationale: string;
}

export interface InternalLinkSuggestions {
  target_url: string;
  suggestions: LinkSuggestion[];
}

export function getQaSummary(
  token: string,
  organizationId: string,
  websiteId: string,
  changeId: string
) {
  return request<QaSummary>(
    `/organizations/${organizationId}/websites/${websiteId}/change-records/${changeId}/qa-summary`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function getWeeklyStrategy(token: string, organizationId: string, websiteId: string) {
  return request<StrategySummary>(
    `/organizations/${organizationId}/websites/${websiteId}/strategy`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function listOrphanPages(token: string, organizationId: string, websiteId: string) {
  return request<Page[]>(`/organizations/${organizationId}/websites/${websiteId}/orphan-pages`, {
    headers: authHeaders(token),
  });
}

export function getInternalLinkSuggestions(
  token: string,
  organizationId: string,
  websiteId: string,
  pageId: string
) {
  return request<InternalLinkSuggestions>(
    `/organizations/${organizationId}/websites/${websiteId}/pages/${pageId}/internal-link-suggestions`,
    { method: "POST", headers: authHeaders(token) }
  );
}

// --- Agency multi-client overview ---

export interface WebsiteOverviewRow {
  website_id: string;
  display_name: string;
  hostname: string;
  verification_status: string;
  status: string;
  open_findings_count: number;
  open_opportunities_count: number;
  pending_tasks_count: number;
  last_crawl_at: string | null;
  last_crawl_status: string | null;
}

export function getOrganizationOverview(token: string, organizationId: string) {
  return request<WebsiteOverviewRow[]>(`/organizations/${organizationId}/overview`, {
    headers: authHeaders(token),
  });
}

// --- Organization settings (Slack notifications) ---

export interface OrganizationResponse {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
}

export function updateOrganizationSettings(
  token: string,
  organizationId: string,
  payload: { slack_webhook_url: string | null }
) {
  return request<OrganizationResponse>(`/organizations/${organizationId}/settings`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export function sendSlackTestNotification(token: string, organizationId: string) {
  return request<{ status: string }>(`/organizations/${organizationId}/notifications/slack/test`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export function rotateDeployWebhookSecret(token: string, organizationId: string, websiteId: string) {
  return request<{ secret: string }>(
    `/organizations/${organizationId}/websites/${websiteId}/webhooks/deploy/rotate-secret`,
    { method: "POST", headers: authHeaders(token) }
  );
}

// --- Guided onboarding ---

export interface OnboardingStep {
  key: string;
  title: string;
  mandatory: boolean;
  completed: boolean;
  skipped: boolean;
  detail: string;
}

export interface OnboardingStatus {
  steps: OnboardingStep[];
  welcomed_at: string | null;
  completed_at: string | null;
  all_mandatory_complete: boolean;
}

export function getOnboardingStatus(token: string, organizationId: string) {
  return request<OnboardingStatus>(`/organizations/${organizationId}/onboarding`, {
    headers: authHeaders(token),
  });
}

export function dismissOnboardingWelcome(token: string, organizationId: string) {
  return request<OnboardingStatus>(`/organizations/${organizationId}/onboarding/dismiss-welcome`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export function skipOnboardingStep(token: string, organizationId: string, stepKey: string) {
  return request<OnboardingStatus>(`/organizations/${organizationId}/onboarding/skip`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ step_key: stepKey }),
  });
}

export function unskipOnboardingStep(token: string, organizationId: string, stepKey: string) {
  return request<OnboardingStatus>(`/organizations/${organizationId}/onboarding/unskip`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ step_key: stepKey }),
  });
}

export function completeOnboarding(token: string, organizationId: string) {
  return request<OnboardingStatus>(`/organizations/${organizationId}/onboarding/complete`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

// --- AI Knowledge Assistant chat ---

export interface ChatConversation {
  id: string;
  title: string;
  created_at: string;
}

export interface ChatSource {
  document_id: string;
  title: string;
  category: string;
  suggested_path: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: ChatRole;
  content: string;
  sources: ChatSource[];
  created_at: string;
}

export function listChatConversations(token: string, organizationId: string) {
  return request<ChatConversation[]>(`/organizations/${organizationId}/chat/conversations`, {
    headers: authHeaders(token),
  });
}

export function listChatMessages(token: string, organizationId: string, conversationId: string) {
  return request<ChatMessage[]>(`/organizations/${organizationId}/chat/conversations/${conversationId}/messages`, {
    headers: authHeaders(token),
  });
}

export function askAssistant(
  token: string,
  organizationId: string,
  question: string,
  conversationId: string | null,
  context?: Record<string, unknown>
) {
  return request<ChatMessage>(`/organizations/${organizationId}/chat/messages`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ question, conversation_id: conversationId, context }),
  });
}

export function submitChatFeedback(
  token: string,
  organizationId: string,
  messageId: string,
  rating: "up" | "down"
) {
  return request<void>(`/organizations/${organizationId}/chat/messages/${messageId}/feedback`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ rating }),
  });
}

// --- Admin: knowledge base management (platform admins only) ---

export interface AdminKnowledgeDocument {
  id: string;
  title: string;
  category: string;
  content: string;
  source_type: "seed_docs" | "admin_authored";
  source_key: string;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeIngestionJob {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  documents_processed: number;
  chunks_created: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface AdminChatFeedback {
  id: string;
  message_id: string;
  rating: "up" | "down";
  note: string | null;
  question: string;
  answer: string;
  created_at: string;
}

export function listAdminKnowledgeDocuments(token: string) {
  return request<AdminKnowledgeDocument[]>("/admin/knowledge/documents", { headers: authHeaders(token) });
}

export function createAdminKnowledgeDocument(
  token: string,
  payload: { title: string; category: string; content: string }
) {
  return request<AdminKnowledgeDocument>("/admin/knowledge/documents", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export function updateAdminKnowledgeDocument(
  token: string,
  documentId: string,
  payload: { title?: string; category?: string; content?: string; is_active?: boolean }
) {
  return request<AdminKnowledgeDocument>(`/admin/knowledge/documents/${documentId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export function runKnowledgeReindex(token: string) {
  return request<KnowledgeIngestionJob>("/admin/knowledge/reindex", {
    method: "POST",
    headers: authHeaders(token),
  });
}

export function listKnowledgeIngestionJobs(token: string) {
  return request<KnowledgeIngestionJob[]>("/admin/knowledge/ingestion-jobs", { headers: authHeaders(token) });
}

export function listAdminChatFeedback(token: string, unansweredOnly: boolean) {
  return request<AdminChatFeedback[]>(`/admin/knowledge/feedback?unanswered_only=${unansweredOnly}`, {
    headers: authHeaders(token),
  });
}

// --- Growth recommendations ---

export type RecommendationStatus = "open" | "approved" | "rejected" | "done";

export type LifecycleStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "in_progress"
  | "applied"
  | "validation_pending"
  | "validated"
  | "failed"
  | "rolled_back";

export interface RecrawlResult {
  status: "queued" | "running" | "validated" | "mismatch" | "failed" | "not_applicable" | "not_started";
  url?: string;
  expected?: string | null;
  found?: string | null;
  http_status?: number | null;
  error?: string | null;
  completed_at?: string | null;
}

export interface LifecycleTask {
  recrawl?: RecrawlResult | null;
  task_id: string;
  operation: string;
  target_url: string | null;
  proposed_value: string | null;
  summary: string | null;
  task_status: string;
  approval_status: string;
  state: string;
  change_record_id: string | null;
  before_value: string | null;
  applied_value: string | null;
  connector: string | null;
}

export interface LiveCheck {
  checked_at: string;
  matched: boolean;
  checks: { operation: string; url: string; expected: string | null; found: string | null; matched: boolean; error: string | null }[];
}

export interface RecommendationLifecycle {
  lifecycle_status?: LifecycleStatus;
  supported?: boolean;
  unsupported_reason?: string | null;
  applied_manually?: boolean;
  tasks?: LifecycleTask[];
  live_check?: LiveCheck | null;
}

export interface GrowthRecommendation {
  lifecycle: RecommendationLifecycle;
  id: string;
  recommendation_type: string;
  title: string;
  page_id: string | null;
  proposed_url: string | null;
  opportunity_id: string | null;
  target_country: string | null;
  keyword: string | null;
  data_source: string;
  problem: string;
  recommended_action: string;
  expected_benefit: string;
  priority: "low" | "medium" | "high";
  difficulty: "low" | "medium" | "high";
  automation_available: boolean;
  requires_approval: boolean;
  validation_method: string;
  evidence_json: Record<string, unknown>;
  status: RecommendationStatus;
  updated_at: string;
}

export function listGrowthRecommendations(token: string, organizationId: string, websiteId: string) {
  return request<GrowthRecommendation[]>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations`,
    { headers: authHeaders(token) }
  );
}

export function generateGrowthRecommendations(
  token: string,
  organizationId: string,
  websiteId: string,
  country?: string
) {
  const query = country ? `?country=${encodeURIComponent(country)}` : "";
  return request<GrowthRecommendation[]>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations/generate${query}`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export function updateGrowthRecommendationStatus(
  token: string,
  organizationId: string,
  websiteId: string,
  recommendationId: string,
  status: RecommendationStatus
) {
  return request<GrowthRecommendation>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations/${recommendationId}`,
    { method: "PATCH", headers: authHeaders(token), body: JSON.stringify({ status }) }
  );
}

export function sendGrowthRecommendationToExecution(
  token: string,
  organizationId: string,
  websiteId: string,
  recommendationId: string
) {
  return request<GrowthRecommendation>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations/${recommendationId}/send-to-execution`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export interface SearchWindowStats {
  clicks: number;
  impressions: number;
  ctr: number | null;
  average_position: number | null;
}

export interface PerformanceTimelineEntry {
  change_id: string;
  page_id: string;
  page_url: string | null;
  operation: string | null;
  implemented_at: string;
  validation_status: string;
  before: SearchWindowStats | null;
  after: SearchWindowStats | null;
  after_window_complete: boolean;
  organic_landing_before: { sessions: number; engaged_sessions: number; conversions: number } | null;
  organic_landing_after: { sessions: number; engaged_sessions: number; conversions: number } | null;
  site_ga4_before: { sessions: number; conversions: number } | null;
  site_ga4_after: { sessions: number; conversions: number } | null;
}

export interface PerformanceTimeline {
  window_days: number;
  caveat: string;
  entries: PerformanceTimelineEntry[];
}

export function getPerformanceTimeline(token: string, organizationId: string, websiteId: string, windowDays: number) {
  return request<PerformanceTimeline>(
    `/organizations/${organizationId}/websites/${websiteId}/performance-timeline?window_days=${windowDays}`,
    { headers: authHeaders(token) }
  );
}

export interface AiUsage {
  days: number;
  by_agent_type: {
    agent_type: string;
    runs: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
  }[];
  total_estimated_cost_usd: number;
  note: string;
}

export function getWebsiteAiUsage(token: string, organizationId: string, websiteId: string) {
  return request<AiUsage>(`/organizations/${organizationId}/websites/${websiteId}/ai-usage`, {
    headers: authHeaders(token),
  });
}


export function verifyGrowthRecommendationLive(
  token: string,
  organizationId: string,
  websiteId: string,
  recommendationId: string
) {
  return request<LiveCheck>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations/${recommendationId}/verify-live`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export interface DryRunResult {
  operation: string;
  target_url: string;
  before_value: string;
  proposed_value: string;
  changed: boolean;
}

export function dryRunTask(token: string, organizationId: string, websiteId: string, taskId: string) {
  return request<DryRunResult>(
    `/organizations/${organizationId}/websites/${websiteId}/tasks/${taskId}/dry-run`,
    { method: "POST", headers: authHeaders(token) }
  );
}

export interface CountryOption {
  code: string;
  name: string;
}

export function listCountries(token: string) {
  return request<CountryOption[]>(`/reference/countries`, { headers: authHeaders(token) });
}


export function recrawlGrowthRecommendation(
  token: string,
  organizationId: string,
  websiteId: string,
  recommendationId: string
) {
  return request<GrowthRecommendation>(
    `/organizations/${organizationId}/websites/${websiteId}/growth-recommendations/${recommendationId}/recrawl`,
    { method: "POST", headers: authHeaders(token) }
  );
}


// --- Billing (per-project subscriptions) ---

export interface BillingPlan {
  interval: "month" | "year";
  price_cents: number;
  currency: string;
  trial_days: number;
  monthly_equivalent_cents: number;
}

export interface BillingSubscription {
  id: string;
  status: "trialing" | "active" | "past_due" | "unpaid" | "paused" | "cancelled" | "expired" | "refunded";
  provider: string;
  complimentary: boolean;
  interval: "month" | "year";
  price_cents: number;
  currency: string;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  renews_at: string | null;
  ends_at: string | null;
  cancelled_at: string | null;
  cancellation_scheduled: boolean;
  grace_ends_at: string | null;
  replacements_used: number;
  replacement_limit: number;
  replacements_remaining: number;
  customer_portal_url: string | null;
  update_payment_url: string | null;
}

export interface BillingPayment {
  id: string;
  amount_cents: number;
  currency: string;
  status: "paid" | "failed" | "pending" | "refunded" | "partially_refunded";
  refunded_cents: number;
  billing_reason: string | null;
  paid_at: string | null;
  created_at: string | null;
}

export interface BillingProject {
  website_id: string;
  display_name: string;
  hostname: string;
  target_countries: string[];
  entitlement: { entitled: boolean; reason: string; message: string; until: string | null };
  subscription: BillingSubscription | null;
  payments: BillingPayment[];
  can_start_plan: boolean;
  trial_available: boolean;
}

export interface BillingOverview {
  enforcement: "off" | "log" | "enforce";
  plans: BillingPlan[];
  annual_saving_cents: number;
  projects: BillingProject[];
}

export interface CheckoutStarted {
  checkout_url: string;
  interval: "month" | "year";
  price_cents: number;
  currency: string;
  with_trial: boolean;
  trial_days: number;
  first_charge_at: string | null;
  expires_at: string | null;
}

export function getBillingOverview(token: string, organizationId: string) {
  return request<BillingOverview>(`/organizations/${organizationId}/billing/overview`, { headers: authHeaders(token) });
}

export function startCheckout(token: string, organizationId: string, websiteId: string, interval: "month" | "year") {
  return request<CheckoutStarted>(`/organizations/${organizationId}/websites/${websiteId}/billing/checkout`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ interval }),
  });
}

export interface ReplacementTargets {
  replacements_remaining: number;
  targets: { id: string; display_name: string; hostname: string }[];
}

export function getReplacementTargets(token: string, organizationId: string, subscriptionId: string) {
  return request<ReplacementTargets>(
    `/organizations/${organizationId}/billing/subscriptions/${subscriptionId}/replacement-targets`,
    { headers: authHeaders(token) }
  );
}

export function replaceSubscriptionProject(
  token: string,
  organizationId: string,
  subscriptionId: string,
  targetWebsiteId: string
) {
  return request<{ subscription_id: string; website_id: string; replacements_remaining: number; sequence: number }>(
    `/organizations/${organizationId}/billing/subscriptions/${subscriptionId}/replace-project`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ target_website_id: targetWebsiteId, confirm: true, acknowledge_permanent: true }),
    }
  );
}


// ---------------------------------------------------------------- AI Search Opportunity Finder

export type AiSearchTier = "high_opportunity" | "content_gap" | "ranking_improvement" | "low_priority";
export type AiSearchStatus = "new" | "ready_for_review" | "approved" | "rejected" | "implemented" | "validation_failed" | "monitoring" | "completed";

export interface AiSearchFactor { factor: string; points: number; max: number; note: string }

export interface AiSearchOpportunity {
  query: string;
  categories: string[];
  category_signals: string[];
  country: string | null;
  countries: Record<string, number>;
  impressions: number;
  clicks: number;
  ctr: number;
  average_position: number;
  score: number;
  tier: AiSearchTier;
  factors: AiSearchFactor[];
  needs_review: boolean;
  trend: string;
  landing_page: { page_id: string; url: string } | null;
  other_pages: { page_id: string; url: string; impressions: number }[];
  finding_id: string | null;
  status: AiSearchStatus;
}

export interface AiSearchSummary {
  window: { start: string; end: string };
  data_coverage: { first_day: string | null; last_day: string | null; rows: number };
  warnings: string[];
  explanation: string;
  totals: {
    conversational_queries: number; question_queries: number; long_tail_queries: number; comparison_queries: number;
    problem_solution_queries: number; classified_queries: number; high_opportunity: number; potential_content_gaps: number;
    pages_with_opportunities: number;
  };
  ai_platform_visibility: string;
}

export interface AiSearchOpportunityList {
  items: AiSearchOpportunity[]; page: number; page_size: number; total: number; pages: number;
  warnings: string[]; explanation: string;
}

export interface AiSearchCheck { check: string; status: string; evidence?: string; advice?: string; detail?: string }

export interface AiSearchDraft {
  search_intent: string; user_question: string; page_matches_intent: boolean; intent_note: string; current_answer_assessment: string;
  missing_information: string[]; needs_owner_input: string[]; direct_answer: string; suggested_heading: string; faq_recommended: boolean;
  faq_suggestions: { question: string; answer: string }[]; supporting_examples: string[];
  internal_links: { anchor_text: string; target_url: string }[]; schema_review_note: string; rationale: string; confidence: number;
}

export interface AiSearchFinding {
  id: string; query: string; status: AiSearchStatus; tier: AiSearchTier; score: number; needs_review: boolean;
  target_page: { page_id: string | null; url: string | null };
  answer_analysis: { level: string; reason: string; matching_heading?: string | null; missing_terms?: string[] };
  ai_search_readiness: { label: string; checks: AiSearchCheck[]; passed?: number; total?: number; disclaimer?: string; ai_visibility: string };
  ai_status: string; ai_error: string | null; draft: AiSearchDraft | null;
  quality: { checks: AiSearchCheck[]; blocked: boolean; label: string } | null;
  confidence: number | null; edited_by_user: boolean; label: string;
  recommendation: { id: string; status: string; priority: string; difficulty: string; problem: string; recommended_action: string;
    expected_benefit: string; requires_approval: boolean; validation_method: string } | null;
  execution: { automated: boolean; reason: string };
  implemented_at: string | null; implementation_note: string | null;
  live_check: { matched: boolean | null; error: string | null; checked_at: string } | null;
}

export interface AiSearchDetail {
  opportunity: AiSearchOpportunity;
  history: { date: string; impressions: number; clicks: number; average_position: number | null }[];
  finding: AiSearchFinding | null;
}

export interface AiSearchMonitoring {
  implemented_on: string; window_days: number; caveat: string; note: string; after_window_complete: boolean;
  before: { clicks: number; impressions: number; ctr: number | null; average_position: number | null } | null;
  after: { clicks: number; impressions: number; ctr: number | null; average_position: number | null } | null;
  change: { clicks: number; impressions: number; ctr: number | null; average_position: number | null } | null;
  other_changes_in_window: { kind: string; at: string }[];
}

export interface AiSearchFilters {
  range?: string; start?: string; end?: string; country?: string; device?: string; category?: string; tier?: string;
  min_impressions?: string; max_position?: string; max_ctr?: string; min_score?: string; q?: string; recommendation_status?: string;
  sort?: string; direction?: string; page?: number; page_size?: number;
}

function aiSearchQuery(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params as Record<string, string | number | undefined>)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const text = sp.toString();
  return text ? `?${text}` : "";
}

const aiSearchBase = (org: string, site: string) => `/organizations/${org}/websites/${site}/ai-search`;

export function getAiSearchSummary(token: string, org: string, site: string, filters: AiSearchFilters) {
  return request<AiSearchSummary>(`${aiSearchBase(org, site)}/summary${aiSearchQuery({ range: filters.range, start: filters.start, end: filters.end, country: filters.country, device: filters.device })}`, { headers: authHeaders(token) });
}

export function listAiSearchOpportunities(token: string, org: string, site: string, filters: AiSearchFilters) {
  return request<AiSearchOpportunityList>(`${aiSearchBase(org, site)}/opportunities${aiSearchQuery(filters)}`, { headers: authHeaders(token) });
}

export function getAiSearchDetail(token: string, org: string, site: string, query: string, filters: AiSearchFilters) {
  return request<AiSearchDetail>(`${aiSearchBase(org, site)}/opportunities/detail${aiSearchQuery({ query, range: filters.range, start: filters.start, end: filters.end, country: filters.country })}`, { headers: authHeaders(token) });
}

export function analyzeAiSearchQuery(token: string, org: string, site: string, body: { query: string; country?: string; range?: string; start?: string; end?: string }) {
  return request<AiSearchFinding>(`${aiSearchBase(org, site)}/analyze`, { method: "POST", headers: authHeaders(token), body: JSON.stringify(body) });
}

export function editAiSearchDraft(token: string, org: string, site: string, id: string, body: { direct_answer?: string; suggested_heading?: string }) {
  return request<AiSearchFinding>(`${aiSearchBase(org, site)}/findings/${id}/draft`, { method: "PATCH", headers: authHeaders(token), body: JSON.stringify(body) });
}

export function decideAiSearchFinding(token: string, org: string, site: string, id: string, decision: "approve" | "reject" | "recheck") {
  return request<AiSearchFinding>(`${aiSearchBase(org, site)}/findings/${id}/${decision}`, { method: "POST", headers: authHeaders(token) });
}

export function markAiSearchImplemented(token: string, org: string, site: string, id: string, note: string) {
  return request<AiSearchFinding>(`${aiSearchBase(org, site)}/findings/${id}/mark-implemented`, { method: "POST", headers: authHeaders(token), body: JSON.stringify({ note }) });
}

export function getAiSearchMonitoring(token: string, org: string, site: string, id: string, windowDays = 28) {
  return request<AiSearchMonitoring>(`${aiSearchBase(org, site)}/findings/${id}/monitoring?window_days=${windowDays}`, { headers: authHeaders(token) });
}

export interface AiCrawlerRow { token: string; vendor: string; role: string; meaning: string; state: string; note: string }

export interface AiCrawlerAccess {
  rows: AiCrawlerRow[];
  summary: { search_crawlers_blocked: string[]; training_crawlers_blocked: string[]; unknown: boolean };
  problem: string | null;
  note: string;
}

export function getAiCrawlerAccess(token: string, org: string, site: string) {
  return request<AiCrawlerAccess>(`${aiSearchBase(org, site)}/crawler-access`, { headers: authHeaders(token) });
}

// ---------------------------------------------------------------- History & Progress

export interface HistoryDelta {
  label?: string;
  group?: string;
  source?: string;
  previous: number | null;
  current: number | null;
  change: number | null;
  change_pct: number | null;
  status: "improved" | "declined" | "unchanged" | "changed" | "not_available" | "not_comparable" | "low_volume";
}

export interface HistorySnapshotMeta {
  id: string; taken_at: string; type: string; is_baseline: boolean; status: string; reconstructed: boolean;
  analysis_version: string; scoring_version: string; partial_reason: string | null;
  health_overall?: number | null; open_issues?: number | null; pages_crawled?: number | null;
}

export interface HistoryOverview {
  baseline: HistorySnapshotMeta | null;
  latest: HistorySnapshotMeta | null;
  health: HistoryDelta & { initial: number | null; note: string; like_for_like?: { components: string[]; previous: number; current: number } };
  issues: { identified_total: number; resolved: number; still_open: number; new_since_baseline: number | null; note: string };
  work: { pages_optimized: number; changes_applied?: number; changes_validated?: number; changes_failed?: number; recommendations_implemented: number; recommendations_validated: number; recommendations_failed: number };
  data_sources: Record<string, { available: boolean; reason: string | null }>;
  baseline_performance: { available: boolean; reason?: string } | null;
}

export interface HistoryCompare {
  from: HistorySnapshotMeta;
  to: HistorySnapshotMeta;
  comparison_period: { start: string; end: string };
  rows: HistoryDelta[];
  issue_changes: { available: boolean; resolved?: number; new?: number; still_open?: number; reason?: string };
  warnings: string[];
}

export interface HistorySearchWindow { start: string; end: string; days: number; days_with_data: number; coverage: number; available: boolean }

export interface HistorySearchComparison {
  available: boolean;
  reason?: string;
  against?: string;
  previous?: HistorySearchWindow;
  current?: HistorySearchWindow;
  rows: HistoryDelta[];
  warnings?: string[];
  freshness: { latest_data_date: string | null; last_synced_at: string | null; note: string };
  note?: string;
}

export interface HistorySeries {
  metric: string; label: string; family: string; source: string; start: string; end: string; available: boolean; note: string;
  points: { date: string; value: number | null; reconstructed?: boolean; origin?: string }[];
}

export interface HistoryEvent { id: string; category: string; event_type: string; title: string; occurred_at: string; detail: Record<string, unknown> }

const historyBase = (org: string, site: string) => `/organizations/${org}/websites/${site}/history`;

export function getHistoryOverview(token: string, org: string, site: string) {
  return request<HistoryOverview>(`${historyBase(org, site)}/overview`, { headers: authHeaders(token) });
}

export function listHistorySnapshots(token: string, org: string, site: string) {
  return request<{ items: HistorySnapshotMeta[]; total: number }>(`${historyBase(org, site)}/snapshots?page_size=100`, { headers: authHeaders(token) });
}

export function getHistoryCompare(token: string, org: string, site: string, from: string, to: string) {
  return request<HistoryCompare>(`${historyBase(org, site)}/compare?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, { headers: authHeaders(token) });
}

export function getHistorySearchComparison(token: string, org: string, site: string, period: string, against: string, start?: string, end?: string) {
  const q = new URLSearchParams({ period, against });
  if (period === "custom" && start && end) { q.set("start", start); q.set("end", end); }
  return request<HistorySearchComparison>(`${historyBase(org, site)}/search-comparison?${q.toString()}`, { headers: authHeaders(token) });
}

export function getHistorySeries(token: string, org: string, site: string, metric: string, days: number) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return request<HistorySeries>(`${historyBase(org, site)}/series?metric=${metric}&start=${iso(start)}&end=${iso(end)}`, { headers: authHeaders(token) });
}

export function getHistoryTimeline(token: string, org: string, site: string, category: string, page: number) {
  const q = new URLSearchParams({ page: String(page), page_size: "20" });
  if (category) q.set("category", category);
  return request<{ items: HistoryEvent[]; page: number; pages: number; total: number }>(`${historyBase(org, site)}/timeline?${q.toString()}`, { headers: authHeaders(token) });
}

// ---- Growth plan: journey, 30-day plan, unified recommendations, business profile
export interface GrowthJourney {
  mode: "analysing" | "baseline" | "connected"; message: string;
  baseline: { taken_at: string; reconstructed: boolean } | null; last_analysis_at: string | null;
  integrations: { google_search_console: { connected: boolean; has_data: boolean }; ga4: { connected: boolean; has_data: boolean }; cms: string | null };
  panels: { panel: string; available: boolean; source: string; reason: string | null }[];
  next_actions: { key: string; text: string; detail: string | null }[];
  recommendations: { total: number; by_priority: Record<string, number>; by_type: Record<string, number>; by_stage: Record<string, number> };
  expectations: string;
}

export interface GrowthPlanItem { text: string; status: "todo" | "done" | "blocked"; basis: string; count: number | null }
export interface GrowthPlan {
  generated_from: { pages: number; open_issues: number; critical_issues: number; open_recommendations: number };
  size_class: string; pace_note: string; disclaimer: string; generated_at: string;
  stages: { days: string; title: string; items: GrowthPlanItem[] }[];
}

export interface UnifiedRecommendation {
  id: string; kind: string; title: string; affected: string | null; type: string; problem: string; evidence: Record<string, unknown>; why_it_matters: string;
  suggested_solution: string; implementation: string; priority: string; effort: string; benefit_category: string; validation: string; stage: string; actions: string[]; data_source: string;
}
export interface UnifiedRecommendationList {
  items: UnifiedRecommendation[]; page: number; page_size: number; total: number; pages: number;
  summary: { total: number; by_priority: Record<string, number>; by_type: Record<string, number>; by_stage: Record<string, number> };
}

export interface BusinessProfile {
  exists: boolean; confirmed: boolean; business_type: string | null; industry: string | null; offerings: string[]; target_customers: string[]; objective: string | null;
  known_competitors: string[]; confirmed_at: string | null; target_countries?: string[]; target_language?: string;
  ai_suggestions: null | {
    business_type?: string; industry?: string; offerings?: string[]; audiences?: string[]; search_topics?: string[]; objective_ideas?: string[];
    dropped_unsupported_offerings?: string[]; label?: string; generated_at?: string;
  };
}
export type BusinessProfileInput = Pick<BusinessProfile, "business_type" | "industry" | "offerings" | "target_customers" | "objective" | "known_competitors">;

const growthBase = (org: string, site: string) => `/organizations/${org}/websites/${site}`;

export function getGrowthJourney(token: string, org: string, site: string) {
  return request<GrowthJourney>(`${growthBase(org, site)}/growth/journey`, { headers: authHeaders(token) });
}
export function getGrowthPlan(token: string, org: string, site: string) {
  return request<GrowthPlan>(`${growthBase(org, site)}/growth/plan`, { headers: authHeaders(token) });
}
export function listUnifiedRecommendations(token: string, org: string, site: string, filters: { type?: string; priority?: string; stage?: string; q?: string; page?: number }) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v) q.set(k, String(v));
  return request<UnifiedRecommendationList>(`${growthBase(org, site)}/growth/recommendations?${q.toString()}`, { headers: authHeaders(token) });
}
export function getBusinessProfile(token: string, org: string, site: string) {
  return request<BusinessProfile>(`${growthBase(org, site)}/business-profile`, { headers: authHeaders(token) });
}
export function saveBusinessProfile(token: string, org: string, site: string, body: BusinessProfileInput) {
  return request<BusinessProfile>(`${growthBase(org, site)}/business-profile`, { method: "PUT", headers: authHeaders(token), body: JSON.stringify(body) });
}
export function suggestBusinessProfile(token: string, org: string, site: string) {
  return request<BusinessProfile>(`${growthBase(org, site)}/business-profile/suggest`, { method: "POST", headers: authHeaders(token) });
}

// ---- Shopify SEO: catalog, AI proposals (read-only sync; changes only after approval)
export interface ShopifyIssue { code: string; severity: string; message: string; field: string }
export interface ShopifyItem { id: string; external_id: string; handle: string | null; url: string | null; title: string | null; seo_title: string | null; meta_description: string | null; issues: ShopifyIssue[]; captured_at: string }
export interface ShopifySummary { products: number; collections: number; products_with_issues: number; issue_counts: Record<string, number>; last_synced_at: string | null }
export interface ShopifyProposal {
  id: string; external_id: string; title: string | null; field: string; before_value: string | null; proposed_value: string; rationale: string | null;
  status: string; verified: boolean | null; failure: string | null; label: string;
}
const shopBase = (org: string, site: string) => `/organizations/${org}/websites/${site}/shopify`;
export const getShopifySummary = (t: string, o: string, s: string) => request<ShopifySummary>(`${shopBase(o, s)}/summary`, { headers: authHeaders(t) });
export const syncShopify = (t: string, o: string, s: string) => request<{ products: number; collections: number; summary: ShopifySummary }>(`${shopBase(o, s)}/sync`, { method: "POST", headers: authHeaders(t) });
export const getShopifyCatalog = (t: string, o: string, s: string, kind: "products" | "collections") =>
  request<{ items: ShopifyItem[]; total: number }>(`${shopBase(o, s)}/catalog?kind=${kind}&page_size=100`, { headers: authHeaders(t) });
export const listShopifyProposals = (t: string, o: string, s: string) => request<{ items: ShopifyProposal[] }>(`${shopBase(o, s)}/proposals`, { headers: authHeaders(t) });
export const proposeShopify = (t: string, o: string, s: string, externalId: string) => request<{ items: ShopifyProposal[] }>(`${shopBase(o, s)}/products/${externalId}/propose`, { method: "POST", headers: authHeaders(t) });
export const decideShopify = (t: string, o: string, s: string, id: string, action: "approve" | "reject", edited?: string) =>
  request<ShopifyProposal>(`${shopBase(o, s)}/proposals/${id}/decision`, { method: "POST", headers: authHeaders(t), body: JSON.stringify({ action, edited_value: edited ?? null }) });
export const applyShopify = (t: string, o: string, s: string, id: string) => request<ShopifyProposal>(`${shopBase(o, s)}/proposals/${id}/apply`, { method: "POST", headers: authHeaders(t) });
export const rollbackShopify = (t: string, o: string, s: string, id: string) => request<ShopifyProposal>(`${shopBase(o, s)}/proposals/${id}/rollback`, { method: "POST", headers: authHeaders(t) });

// ---- Customer progress report
export interface ProgressReport {
  project: { name: string; url: string }; generated_at: string; has_progress: boolean;
  baseline: { taken_at: string } | null; latest: { taken_at: string } | null; period: { start: string; end: string } | null;
  health: { initial: number | null; current: number | null; note: string };
  issues: { identified_total: number; resolved: number; still_open: number; new_since_baseline: number | null };
  work: { pages_optimized: number; recommendations_implemented: number; recommendations_validated: number; recommendations_failed: number };
  highlights: string[]; google: { available: boolean; reason: string | null; lines: string[] };
  data_sources: Record<string, { available: boolean; reason: string | null }>; warnings: string[]; limitations: string[];
  search_monthly?: { month: string; clicks: number; impressions: number; days_with_data: number; days_in_month: number; partial: boolean; impressions_per_day: number | null; clicks_per_day: number | null }[];
  work_timeline?: { applied: number; first_change_at: string | null; last_change_at: string | null; milestones: { date: string; days_after_last_change: number; reached: boolean; label: string }[] };
  improvement_verdict?: string;
  site_quality?: { available: boolean; note: string; items: { label: string; first: number | null; latest: number | null; change: number | null; comparable: boolean; confidence: string | null }[] };
}
export const getProgressReport = (t: string, o: string, s: string) => request<ProgressReport>(`/organizations/${o}/websites/${s}/history/report`, { headers: authHeaders(t) });

// ---- Title repair (brand shown twice in page titles)
export interface TitleRepairPlan {
  candidates: { url: string; live_title: string; new_title: string; final_title?: string; final_length?: number; too_long?: boolean }[];
  skipped_already_pending: number; skipped: Record<string, number>; reason_none: string | null; pages_with_applied_titles: number; stopped_early: boolean;
}
export const planTitleRepair = (t: string, o: string, s: string, limit: number) =>
  request<TitleRepairPlan>(`/organizations/${o}/websites/${s}/title-repair/plan?limit=${limit}`, { method: "POST", headers: authHeaders(t) });
export const createTitleRepairTasks = (t: string, o: string, s: string, limit: number) =>
  request<{ created: number; message: string; plan: TitleRepairPlan }>(`/organizations/${o}/websites/${s}/title-repair/tasks?limit=${limit}`, { method: "POST", headers: authHeaders(t) });

// ---- Authority & backlinks (free-first, no paid link index) ----
export type AuthoritySignal = { key: string; label: string; value: number | null; weight: number; status: "calculated" | "not_available"; how: string; inputs: Record<string, unknown>; note: string | null; contribution?: number | null };
export type AuthorityAssessmentData = { id: string; computed_at: string; formula_version: string; domain_quality: number | null; coverage: number; confidence: string; signals: AuthoritySignal[]; inputs: Record<string, unknown>; data_source: string };
export type AuthorityResponse = {
  disclaimer: string; latest: AuthorityAssessmentData | null; empty_reason: string | null;
  comparison: null | { available: boolean; reason?: string; domain_quality_change?: number | null; note?: string | null; signals?: { key: string; label: string; previous: number | null; current: number | null; change: number | null; status: string }[] };
  history: { computed_at: string; domain_quality: number | null; coverage: number; confidence: string; formula_version: string }[];
};
export type BacklinkItem = { id: string; source_url: string; source_domain: string; target_url: string | null; anchor_text: string | null; rel_values: string[]; is_nofollow: boolean | null; link_location: string | null; discovery_source: string; status: string; http_status: number | null; first_discovered_at: string; last_checked_at: string | null; last_live_at: string | null; lost_at: string | null; note: string | null; data_source: string };
export type BacklinkAnalysis = { label: string; recorded: number; verified_live: number; by_status: Record<string, number>; unchecked: number; referring_domains: number; followed: number; nofollow_or_ugc_sponsored: number;
  top_domains: { domain: string; links: number }[]; anchor_distribution: { anchor: string; links: number; share: number }[]; destination_pages: { url: string; links: number }[]; single_domain_share: number | null; lost: { source_url: string; lost_at: string | null }[] };
export type BacklinkList = { items: BacklinkItem[]; analysis: BacklinkAnalysis; limits: { max_import: number; max_checks_per_call: number }; empty_reason: string | null };
const authorityBase = (org: string, site: string) => `/organizations/${org}/websites/${site}`;
export function getAuthority(token: string, org: string, site: string) { return request<AuthorityResponse>(`${authorityBase(org, site)}/authority`, { headers: authHeaders(token) }); }
export function refreshAuthority(token: string, org: string, site: string) { return request<AuthorityAssessmentData>(`${authorityBase(org, site)}/authority/refresh`, { method: "POST", headers: authHeaders(token) }); }
export function listBacklinks(token: string, org: string, site: string) { return request<BacklinkList>(`${authorityBase(org, site)}/backlinks`, { headers: authHeaders(token) }); }
export function importBacklinks(token: string, org: string, site: string, body: { text: string; source: "user_provided" | "gsc_export" }) {
  return request<{ added: number; duplicates: number; rejected: { url: string; reason: string }[]; truncated: number }>(`${authorityBase(org, site)}/backlinks/import`, { method: "POST", headers: authHeaders(token), body: JSON.stringify(body) });
}
export function checkBacklinks(token: string, org: string, site: string) { return request<{ checked: number; remaining_in_batch: number; analysis: BacklinkAnalysis }>(`${authorityBase(org, site)}/backlinks/check`, { method: "POST", headers: authHeaders(token) }); }
export function deleteBacklink(token: string, org: string, site: string, id: string) { return request<void>(`${authorityBase(org, site)}/backlinks/${id}`, { method: "DELETE", headers: authHeaders(token) }); }

export type RankingOpportunities = { available: boolean; reason: string | null; label?: string; formula_version: string; items: { query: string; page_url: string | null; impressions: number; clicks: number; position: number; score: number; confidence: string; data_source: string }[] };
export function getRankingOpportunities(token: string, org: string, site: string) { return request<RankingOpportunities>(`/organizations/${org}/websites/${site}/keywords/ranking-opportunities`, { headers: authHeaders(token) }); }

// ---- Free-first intelligence (content, technical, lab, competitors, keywords) ----
export type IntelKind = "content" | "technical" | "lab" | "competitors" | "keywords";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type IntelRun = { computed_at?: string; formula_version?: string; score?: number | null; coverage?: number | null; available?: boolean; data_source?: string; reason?: string | null; [k: string]: any };
export type IntelResponse = { latest: IntelRun | null; history: { computed_at: string; score: number | null; coverage: number | null; formula_version: string }[]; empty_reason: string | null };
export function getIntel(token: string, org: string, site: string, kind: IntelKind) { return request<IntelResponse>(`/organizations/${org}/websites/${site}/intelligence/${kind}`, { headers: authHeaders(token) }); }
export function runIntel(token: string, org: string, site: string, kind: IntelKind) { return request<IntelRun>(`/organizations/${org}/websites/${site}/intelligence/${kind}/run`, { method: "POST", headers: authHeaders(token), body: JSON.stringify({}) }); }
