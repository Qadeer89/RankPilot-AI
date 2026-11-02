# RankPilot AI --- Database Schema Specification

## 1. Design requirements

Use PostgreSQL. All customer-owned records must be tenant-scoped. Use
UUID primary keys, UTC timestamps, explicit status enums, indexes for
common filters and migrations for every schema change. Enforce tenant
isolation in application queries and, where practical, PostgreSQL
row-level security.

## 2. Core tables

### Identity and tenancy

-   `users`: id, email, password/auth provider reference, status,
    created_at.
-   `organizations`: id, name, slug, plan, status, created_at.
-   `memberships`: organization_id, user_id, role.
-   `subscriptions`: organization_id, provider,
    external_subscription_id, plan, status, period dates.

### Websites and integrations

-   `websites`: id, organization_id, canonical_url, hostname,
    display_name, verification_status, platform, timezone,
    automation_policy, crawl_budget, status.
-   `website_verifications`: website_id, method, token_hash,
    verified_at, expires_at.
-   `oauth_connections`: organization_id, provider,
    encrypted_token_reference, scopes, status, expires_at.
-   `website_connections`: website_id, connector_type,
    encrypted_secret_reference, granted_scopes, status,
    last_verified_at.

### Crawling and page intelligence

-   `crawl_jobs`: website_id, trigger, status, started_at, completed_at,
    pages_requested, pages_fetched, error_summary.
-   `pages`: website_id, canonical_url, normalized_url, first_seen_at,
    last_seen_at, last_status_code, indexability_state, content_hash.
-   `page_snapshots`: page_id, crawl_job_id, fetched_at, status_code,
    title, meta_description, canonical_url, robots_directives,
    headings_json, schema_json, internal_links_json,
    content_fingerprint.
-   `crawl_frontier`: website_id, url, priority, discovered_from, state,
    next_fetch_at.

### Findings and opportunities

-   `seo_findings`: website_id, page_id nullable, rule_code, severity,
    confidence, evidence_json, first_detected_at, last_detected_at,
    status.
-   `seo_opportunities`: website_id, page_id nullable, category, title,
    rationale, impact_estimate, confidence, effort_estimate, risk_tier,
    evidence_json, status.
-   `keyword_observations`: website_id, query, page_id nullable, date,
    clicks, impressions, ctr, average_position, source.
-   `competitor_domains`: website_id, domain, source, status; optional
    feature, not MVP dependency.

### AI, tasks and execution

-   `agent_runs`: website_id, agent_type, model, status, input_tokens,
    output_tokens, estimated_cost, started_at, completed_at,
    result_reference.
-   `seo_tasks`: website_id, opportunity_id nullable, task_type, status,
    priority, risk_tier, proposed_change_json, approval_status,
    idempotency_key.
-   `change_records`: website_id, page_id, connector_type,
    before_state_json, after_state_json, actor_type, actor_id,
    approval_id, executed_at, validation_status.
-   `approvals`: seo_task_id, requested_by, decided_by, decision,
    reason, decided_at.
-   `rollback_records`: change_record_id, rollback_method, status,
    initiated_by, completed_at, result_json.

### Reporting, notifications and metering

-   `notifications`: organization_id, website_id, channel, event_type,
    payload_json, status, sent_at.
-   `reports`: organization_id, website_id, period_start, period_end,
    report_type, storage_reference, created_at.
-   `usage_records`: organization_id, website_id, metric, quantity,
    unit, estimated_cost, period_start.
-   `audit_events`: organization_id, actor, action, resource_type,
    resource_id, metadata_json, created_at.

## 3. Optional provider abstraction

When external SEO data providers are introduced, add: -
`data_provider_connections`: organization_id, provider_code,
encrypted_secret_reference, status, terms_version. -
`provider_usage_records`: provider_code, endpoint_code, units,
estimated_cost, request_date.

Do not create provider-specific core tables or make any external
provider required for normal crawling, technical audits or Search
Console ingestion.

## 4. Retention and data minimization

-   Raw HTML should not be stored indefinitely; retain only what is
    needed for snapshots/evidence.
-   Define per-plan crawl and snapshot retention.
-   Apply retention to agent traces, page snapshots, notifications and
    reports.
-   Do not store OpenAI API keys in application tables.
-   Store OAuth tokens encrypted or by reference to a secret store.
-   Customer deletion must cascade or anonymize dependent records
    according to documented retention/legal requirements.
-   Backups must be encrypted and stored outside the VPS.

## 5. Indexing and performance

Index organization_id, website_id, status, created_at, normalized_url,
query/date and task scheduling fields. Partition high-volume time-series
tables only when measured volume justifies it. Avoid premature
partitioning.
