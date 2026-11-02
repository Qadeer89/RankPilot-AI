# RankPilot AI --- Development Work Breakdown

## EPIC 0 --- Infrastructure and repository readiness

-   **RP-0001:** Inspect existing VPS resources, processes, ports, Nginx
    and database services.
-   **RP-0002:** Create isolated RankPilot app user, directory and
    environment files.
-   **RP-0003:** Configure domain/subdomain, TLS and firewall rules.
-   **RP-0004:** Configure encrypted external backup destination and
    restore test.
-   **RP-0005:** Configure OpenAI API key as protected server-side
    secret and spending limits.
-   **RP-0006:** Create repository, branch policy, CI checks and
    environment separation.

## EPIC 1 --- Platform foundation

-   **RP-0101:** Bootstrap Next.js + TypeScript frontend.
-   **RP-0102:** Bootstrap FastAPI backend.
-   **RP-0103:** Configure PostgreSQL schema migrations.
-   **RP-0104:** Configure Redis and Celery worker/scheduler.
-   **RP-0105:** Implement authentication and session security.
-   **RP-0106:** Implement organizations, roles and tenant isolation.
-   **RP-0107:** Add health/readiness endpoints and structured logs.

## EPIC 2 --- Website onboarding

-   **RP-0201:** Website registration and URL normalization.
-   **RP-0202:** SSRF-safe URL validation service.
-   **RP-0203:** Domain ownership verification.
-   **RP-0204:** Website platform detection.
-   **RP-0205:** Website settings, crawl budget and pause controls.

## EPIC 3 --- Crawler and baseline

-   **RP-0301:** Robots.txt and sitemap discovery.
-   **RP-0302:** Bounded HTTP crawler with rate limits.
-   **RP-0303:** HTML extraction and page normalization.
-   **RP-0304:** Selective Playwright rendering fallback.
-   **RP-0305:** Page snapshots and content fingerprints.
-   **RP-0306:** Crawl frontier, deduplication and retry handling.

## EPIC 4 --- Deterministic SEO engine

-   **RP-0401:** HTTP status and redirect checks.
-   **RP-0402:** Indexability, robots and canonical checks.
-   **RP-0403:** Sitemap inclusion checks.
-   **RP-0404:** Title, description and heading checks.
-   **RP-0405:** Structured data parsing checks.
-   **RP-0406:** Internal-link and broken-link checks.
-   **RP-0407:** Findings evidence and dashboard.

## EPIC 5 --- Google data

-   **RP-0501:** Google OAuth flow and secure token storage.
-   **RP-0502:** Search Console property discovery/selection.
-   **RP-0503:** Search Analytics ingestion.
-   **RP-0504:** Freshness, quota and missing-data handling.
-   **RP-0505:** Search performance dashboard.

## EPIC 6 --- OpenAI and opportunity engine

-   **RP-0601:** OpenAI server-side client and configuration.
-   **RP-0602:** Strict structured output schemas.
-   **RP-0603:** Opportunity scoring and prioritization.
-   **RP-0604:** Content/metadata proposal agent.
-   **RP-0605:** Internal-link opportunity agent.
-   **RP-0606:** AI evaluation golden set from founder-owned websites.
-   **RP-0607:** Token usage, estimated cost and budget enforcement.

## EPIC 7 --- Execution and validation

-   **RP-0701:** Risk tiers and automation policy.
-   **RP-0702:** Approval workflow.
-   **RP-0703:** WordPress connector authentication and scope checks.
-   **RP-0704:** Bounded metadata/content operations.
-   **RP-0705:** Before/after change records.
-   **RP-0706:** Post-change deterministic validation.
-   **RP-0707:** Safe rollback adapter where supported.
-   **RP-0708:** Pause/kill switch and audit trail.

## EPIC 8 --- Daily operations and reporting

-   **RP-0801:** Daily scheduler and job orchestration.
-   **RP-0802:** Changed-page and priority-page recrawls.
-   **RP-0803:** Daily opportunity refresh.
-   **RP-0804:** Email notifications.
-   **RP-0805:** Weekly report generation.
-   **RP-0806:** Usage and cost dashboard.
-   **RP-0807:** Retention and cleanup jobs.

## EPIC 9 --- QA and release

-   **RP-0901:** Unit and integration test suites.
-   **RP-0902:** E2E onboarding-to-validation tests.
-   **RP-0903:** SSRF and tenant-isolation security tests.
-   **RP-0904:** AI proposal evaluation and prompt-injection tests.
-   **RP-0905:** Shared VPS load/resource tests.
-   **RP-0906:** Backup/restore and incident runbooks.
-   **RP-0907:** Founder pilot acceptance and beta go/no-go.

## Definition of done

A task is done only when code, tests, security considerations, logging,
error handling, documentation and acceptance evidence are complete. Any
task that can modify a website must include authorization, risk policy,
idempotency and post-change validation.
