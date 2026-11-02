const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, detail);
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
  user: { id: string; email: string };
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
  automation_policy: { auto_execute_risk_tier_1?: boolean };
  search_console_site_url: string | null;
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
  last_verified_at: string | null;
}

export interface SearchPerformanceRow {
  query: string;
  date: string;
  clicks: number;
  impressions: number;
  ctr: number;
  average_position: number;
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

export function getMe(token: string) {
  return request<MeResponse>("/me", { headers: authHeaders(token) });
}

export function listWebsites(token: string, organizationId: string) {
  return request<Website[]>(`/organizations/${organizationId}/websites`, {
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
  payload: { auto_execute_risk_tier_1?: boolean; crawl_budget?: number; display_name?: string }
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

// --- Reports ---

export function listReports(token: string, organizationId: string, websiteId: string) {
  return request<Report[]>(`/organizations/${organizationId}/websites/${websiteId}/reports`, {
    headers: authHeaders(token),
  });
}
