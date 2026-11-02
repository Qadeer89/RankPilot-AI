# RankPilot AI --- API Specification

## 1. API conventions

-   REST JSON API under `/api/v1`.
-   TLS required outside local development.
-   Authenticated requests derive organization membership server-side.
-   All resource queries enforce tenant scope.
-   Use pagination, request IDs, structured errors and idempotency keys
    for writes.
-   Never expose OpenAI or connector secrets to the browser.

## 2. Main endpoint groups

### Authentication and organizations

-   `POST /auth/register`
-   `POST /auth/login`
-   `GET /me`
-   `GET /organizations`
-   `POST /organizations`
-   `GET /organizations/{organization_id}/members`

### Websites

-   `POST /websites` --- register URL.
-   `GET /websites`
-   `GET /websites/{website_id}`
-   `POST /websites/{website_id}/verify`
-   `PATCH /websites/{website_id}/settings`
-   `POST /websites/{website_id}/pause`
-   `DELETE /websites/{website_id}`

### Crawls and audits

-   `POST /websites/{website_id}/crawls`
-   `GET /websites/{website_id}/crawls`
-   `GET /crawls/{crawl_id}`
-   `GET /websites/{website_id}/pages`
-   `GET /websites/{website_id}/findings`
-   `GET /websites/{website_id}/opportunities`

### Search integrations

-   `GET /integrations/google/search-console/connect`
-   `GET /integrations/google/search-console/callback`
-   `GET /websites/{website_id}/search-properties`
-   `POST /websites/{website_id}/search-console/sync`
-   `GET /websites/{website_id}/search-performance`
-   GA4 endpoints are P1.

### AI and execution

-   `POST /opportunities/{opportunity_id}/proposals`
-   `POST /seo-tasks/{task_id}/approve`
-   `POST /seo-tasks/{task_id}/reject`
-   `POST /seo-tasks/{task_id}/execute`
-   `GET /websites/{website_id}/tasks`
-   `GET /change-records/{change_id}`
-   `POST /change-records/{change_id}/rollback`
-   `POST /websites/{website_id}/automation/pause`

### Reporting and usage

-   `GET /websites/{website_id}/reports`
-   `GET /organizations/{organization_id}/usage`
-   `GET /organizations/{organization_id}/audit-events`

## 3. Website onboarding request

``` json
{
  "url": "https://example.com",
  "display_name": "Example Website",
  "purpose": "owned_pilot_site"
}
```

The API must normalize the URL, reject unsafe schemes/hosts, perform
domain verification before recurring monitoring and require connector
authorization before any write action.

## 4. Opportunity proposal contract

``` json
{
  "opportunity_id": "uuid",
  "summary": "Improve missing page titles",
  "evidence": [
    {"page_url": "https://example.com/page", "finding_code": "TITLE_MISSING"}
  ],
  "proposed_actions": [
    {"operation": "set_title", "target_url": "https://example.com/page", "value": "Example title"}
  ],
  "risk_tier": 1,
  "confidence": 0.91,
  "requires_approval": false,
  "validation_plan": ["Fetch page", "Verify title", "Check canonical and robots"]
}
```

The example is illustrative. The backend must validate all AI-generated
proposals against strict schemas and allowed operations.

## 5. Search Console data

Expose clicks, impressions, CTR and average position with date range,
property, dimensions and source freshness. Label the data as aggregated
and potentially delayed. Do not represent average position as a
guaranteed exact live rank.

## 6. Provider adapter contract (future)

Define a provider-neutral interface such as: - `get_keyword_ideas()` -
`get_keyword_metrics()` - `get_backlink_summary()` -
`get_competitor_visibility()`

Adapters must declare licensing/redistribution constraints, quotas, cost
per call and data freshness. No provider adapter is required to run MVP
features.

## 7. Error and safety requirements

Return stable error codes for invalid URL, unverified domain, missing
connector authorization, insufficient scope, quota exceeded, crawl
budget exceeded, approval required, unsafe action and tenant access
denied. Log request IDs but never secrets or full sensitive payloads.
