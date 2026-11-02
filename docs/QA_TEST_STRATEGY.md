# RankPilot AI --- QA Test Strategy

## 1. Quality objectives

Ensure findings are evidence-backed, crawler behavior is safe, AI
proposals are useful and bounded, website changes are authorized, and
post-change validation detects regressions.

## 2. Test environments

-   Local development.
-   Staging environment on a separate hostname or isolated
    configuration.
-   Founder-owned pilot websites, with read-only baseline first.
-   Use staging or reversible low-risk pages for write-operation tests.
-   Never use a live customer site as an uncontrolled experiment.

## 3. Test levels

-   Unit: URL normalization, rule engine, scoring, policy, schemas and
    parsers.
-   Integration: PostgreSQL, Redis, crawler, OpenAI adapter, Search
    Console OAuth and WordPress connector.
-   E2E: onboarding → crawl → findings → proposal → approval → execution
    → validation.
-   Security: SSRF, tenant isolation, secret leakage, OAuth scopes,
    prompt injection and abuse.
-   Load: crawl concurrency, queue backlog, database growth and memory
    pressure on the shared VPS.

## 4. Functional coverage

### Onboarding

-   Valid/invalid URLs, redirects, domain verification, duplicate
    websites, ownership changes.

### Crawling

-   Robots handling, sitemap discovery, canonical URLs, pagination,
    query strings, rate limiting, JS fallback, redirect loops and
    hostile responses.

### SEO rules

-   Missing/duplicate title, meta description, headings, canonical,
    robots directives, HTTP status, sitemap mismatch, broken links and
    schema parse errors.

### Search Console

-   OAuth, property mismatch, token refresh, quotas, delayed data, empty
    results, date ranges and source freshness.

### AI

-   Schema validity, evidence citation, hallucination resistance, prompt
    injection, token limits, retry handling, cost caps and output
    quality.

### Execution

-   No connector/no write, approval required, idempotency, before/after
    state, partial failure, validation failure, rollback and pause
    controls.

### Multi-tenancy

-   Cross-tenant access denial for every resource and background job.

## 5. Pilot evaluation on founder-owned websites

For each pilot website: 1. Record baseline crawl, page count and
findings. 2. Connect Search Console where available. 3. Manually review
high-priority findings. 4. Compare AI proposals with human judgment. 5.
Execute only low-risk approved tests. 6. Validate changes immediately.
7. Observe Search Console trends over suitable periods. 8. Record false
positives, regressions, accepted proposals and cost.

Do not claim a ranking improvement based only on a short observation
window or a single average-position movement.

## 6. Release gates

-   No critical tenant isolation or SSRF defects.
-   No secret leakage.
-   No unauthorized writes in test suite.
-   Deterministic rules meet agreed precision on golden test pages.
-   All writes have before/after evidence and validation.
-   Cost and crawl limits are enforced.
-   Backups and restore procedure are tested.
-   Shared VPS resource usage remains within agreed safety thresholds.
