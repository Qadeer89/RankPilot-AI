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
