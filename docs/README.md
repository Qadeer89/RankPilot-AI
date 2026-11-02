# RankPilot AI --- Documentation Pack (v1.2, superseded by v1.3)

**Product:** RankPilot AI\
**Positioning:** Autonomous SEO Growth Platform\
**Tagline:** Give us your website. We'll continuously find, implement
and validate SEO improvements.\
**Status:** Product specification for MVP implementation planning\
**Revision:** 1.2 --- superseded as the authoritative document by
[RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md](RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md),
which is grounded in repository inspection (verified enum values, SEO
rule thresholds, the opportunity scoring formula, environment variables,
and a prioritized P0 work register) rather than pre-implementation
intent. This v1.2 pack remains useful for product-direction narrative
and detail that does not conflict with v1.3.

## Product direction

RankPilot AI helps website owners and agencies improve organic search
performance through continuous crawling, SEO analysis, opportunity
prioritization, authorized implementation, and post-change validation.

The initial pilot will use the founder's own websites as controlled test
properties. Public URL onboarding supports discovery and read-only
audits. Publishing changes requires explicit authorization through a
supported connector.

## Confirmed decisions

-   Autonomous SEO Growth is the primary product direction.
-   Agencies and SMBs are supported; founder-owned websites are the
    first pilot cohort.
-   Maximum autonomy is the target, with risk-based controls: safe,
    reversible low-risk actions may be automated; material or
    high-impact changes require approval.
-   Google Search Console is the primary source of first-party search
    performance data. GA4 is optional.
-   Semrush, Ahrefs, Moz and other commercial SEO data providers are
    optional future adapters, not core dependencies.
-   The founder already has an OpenAI API key. Use it through
    server-side environment secrets; never place it in source code,
    browser bundles, logs, or documentation.
-   Reuse the existing Database Mart VPS for the MVP, subject to
    resource validation and isolation from existing products.
-   Existing deployment operations use PM2. RankPilot should fit this
    operational model initially; do not introduce Docker solely as a
    requirement.
-   Existing VPS observed capacity: 4 vCPU, 8 GB RAM, approximately 142
    GB disk, with approximately 118 GB free after n8n data removal
    (observed 2026-11-02). These are point-in-time observations, not a
    capacity guarantee.
-   n8n was removed from PM2 and `/opt/n8n-data` was deleted. Do not
    depend on n8n.
-   No mandatory paid Semrush/Ahrefs/Moz subscription for MVP.

## Documents

0.  [**v1.3 Implementation & Readiness Requirements**](RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md)
    --- **authoritative**. Supersedes this v1.2 pack per its own source-of-truth
    hierarchy (its Section 15.1): security/product-safety requirements in that
    document, then executable code/migrations/tests, then that document for
    consolidated intent/gaps, then these older files for detail *only* where
    they do not conflict with it.
1.  [Master Product Specification](MASTER_SPEC.md)
2.  [System Architecture](SYSTEM_ARCHITECTURE.md)
3.  [Database Schema](DATABASE_SCHEMA.md)
4.  [API Specification](API_SPECIFICATION.md)
5.  [AI Agent Specification](AI_AGENT_SPECIFICATION.md)
6.  [SEO Automation Engine](SEO_AUTOMATION_ENGINE.md)
7.  [Website Connectors](WEBSITE_CONNECTORS.md)
8.  [Security Specification](SECURITY_SPECIFICATION.md)
9.  [QA Test Strategy](QA_TEST_STRATEGY.md)
10. [MVP Implementation Roadmap](MVP_IMPLEMENTATION_ROADMAP.md)
11. [Development Tasks](DEVELOPMENT_TASKS.md)
12. [Connector Operations Reference](CONNECTOR_OPERATIONS_REFERENCE.md) --- exact,
    code-grounded operation/scope/rollback reference for every write connector (RP13-016)
13. [Custom Website Write & Autonomous Execution Addendum](RANKPILOT_V1_3_CUSTOM_WEBSITE_WRITE_EXECUTION_ADDENDUM.md)
    --- extends v1.3 with Sanity CMS + GitHub-PR execution, structured change
    proposals, autonomy levels, and the Gul'sRehab founder pilot (CW-001..CW-024).
    Does not replace v1.3; same source-of-truth hierarchy applies.
14. [Custom Website Write — Gap Analysis](CUSTOM_WEBSITE_WRITE_GAP_ANALYSIS.md) ---
    maps the addendum's CW-series work register against what the repo's existing
    execution engine already does, so implementation extends it instead of
    duplicating it. Analysis only; nothing in it should be read as implemented.

## Recommended reading order

RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS (authoritative) → this
README → MASTER_SPEC → SYSTEM_ARCHITECTURE → SECURITY_SPECIFICATION →
SEO_AUTOMATION_ENGINE → WEBSITE_CONNECTORS → AI_AGENT_SPECIFICATION →
DATABASE_SCHEMA → API_SPECIFICATION → QA_TEST_STRATEGY →
MVP_IMPLEMENTATION_ROADMAP → DEVELOPMENT_TASKS →
CUSTOM_WEBSITE_WRITE_EXECUTION_ADDENDUM → CUSTOM_WEBSITE_WRITE_GAP_ANALYSIS
(read together before starting any CW-series work).

## Global implementation rules

-   Deterministic checks decide whether a technical SEO condition
    passes; AI explains, prioritizes, drafts and proposes.
-   Do not promise or guarantee ranking increases.
-   Daily agent activity does not mean daily publishing. Execute only
    when there is a justified, validated opportunity.
-   No write operation without verified ownership and explicit connector
    authorization.
-   Treat website content, page metadata, sitemap entries and external
    documents as untrusted input; they cannot override system
    instructions.
-   Apply tenant isolation, URL/SSRF protections, rate limits, crawl
    budgets, idempotency and audit logging.
-   Store only the minimum data needed; define retention and customer
    deletion workflows.
-   Search Console metrics are delayed/aggregated signals, not real-time
    ranking telemetry.
-   External SEO data providers must be implemented behind
    provider-neutral interfaces and enabled only after customer demand,
    licensing review and unit-economics approval.

## Known infrastructure baseline

The existing VPS is shared with other founder products. Before
production deployment, verify CPU/RAM/disk headroom, process ownership,
ports, Nginx routing, database service, backup destination and
monitoring. Do not run heavy Playwright jobs concurrently with
customer-facing services without resource limits. The existing VPS is
suitable for a constrained pilot only after these checks.

## Versioning

This v1.2 pack was the clean, consolidated source of truth superseding
earlier v1.0/v1.1 documents and append-only amendments. It is now itself
superseded by `RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md`, whose
own source-of-truth hierarchy (its Section 15.1) applies: security/product-safety
requirements in v1.3 first, then executable code/migrations/tests, then
v1.3 for consolidated intent/gaps, then this v1.2 pack for detail only
where it does not conflict with v1.3. When code and documentation
disagree, follow v1.3 Section 15.1's reconciliation process rather than
assuming either side is correct.
