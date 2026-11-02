# RankPilot AI --- Master Product Specification

## 1. Product summary

RankPilot AI is an Autonomous SEO Growth Platform. A customer submits a
website URL; RankPilot discovers the site, establishes an SEO baseline,
identifies opportunities, plans and performs authorized improvements,
validates changes, and reports progress over time.

The first pilot cohort will be the founder's own websites. This allows
controlled testing across real websites before onboarding external
customers.

**Positioning:** Ship validated SEO improvements continuously.\
**Tagline:** Give us your website. We'll continuously find, implement
and validate SEO improvements.

## 2. Problem and product outcome

Website owners often receive SEO audits and long lists of
recommendations but must manually interpret, prioritize, implement and
re-check them. RankPilot closes this loop:

1.  Discover and measure.
2.  Diagnose issues and opportunities.
3.  Prioritize by impact, confidence, effort and risk.
4.  Prepare a change proposal.
5.  Execute only within authorized permissions and risk policy.
6.  Validate the resulting website.
7.  Monitor search performance and learn from outcomes.

Rankings change over time and depend on factors outside RankPilot's
control. The product must not guarantee positions, traffic or revenue.

## 3. Target users

-   **Initial pilot:** Founder-owned websites, with explicit permission
    to crawl and modify them.
-   **Primary commercial segments:** SEO/digital agencies managing
    multiple sites, and SMBs managing their own websites.
-   **Roles:** Owner/admin, agency operator, editor/approver, read-only
    client.

## 4. Core user journey

1.  Create account and workspace.
2.  Submit a canonical website URL.
3.  Complete domain ownership verification for ongoing monitoring and
    any write access.
4.  Run initial crawl and technical/on-page baseline.
5.  Optionally connect Google Search Console; optionally connect GA4.
6.  Select site platform and authorize a supported write connector if
    execution is desired.
7.  Review prioritized opportunities and automation policy.
8.  RankPilot runs scheduled monitoring and analysis.
9.  Eligible low-risk changes are executed; other changes wait for
    approval.
10. Every change is validated and recorded.
11. Dashboard and weekly/monthly reports show work performed and
    observed search outcomes.

## 5. Scope

### MVP / P0

-   Authentication, organizations/workspaces and tenant isolation.
-   Website registration, URL validation, domain verification and
    platform detection.
-   Sitemap/robots discovery and controlled crawler.
-   Page inventory and page snapshots.
-   Deterministic technical and on-page SEO rule engine.
-   SEO baseline and prioritized opportunities.
-   Google Search Console OAuth and supported performance ingestion.
-   OpenAI-powered explanation, prioritization and structured content
    proposals.
-   Daily scheduler and job queue with per-site crawl budgets.
-   Change proposal, approval policy, execution log and post-change
    validation.
-   WordPress connector as first general-purpose write integration, only
    after authorization.
-   Email alerts and dashboard activity feed.
-   Founder-owned websites as first test properties.
-   Usage metering, rate limits, audit logs and operational monitoring.

### P1

-   GA4 integration.
-   Agency multi-client views and client reports.
-   More robust content brief and internal-link recommendations.
-   GitHub/deployment integration for custom-code sites.
-   Additional CMS write connectors (Shopify/Webflow/custom adapters).
-   Slack notifications and branded reporting.

### P2 / optional

-   Provider adapters for Semrush, Ahrefs, Moz or other licensed SEO
    datasets.
-   Advanced SERP tracking and competitor intelligence.
-   Backlink intelligence.
-   Additional analytics and commerce integrations.

### Explicitly out of MVP

-   Building a full Semrush/Ahrefs replacement.
-   Proprietary global backlink index.
-   Guaranteed ranking improvement.
-   Automatic publishing to arbitrary websites without authorized
    access.
-   Unbounded autonomous rewriting or mass page changes.
-   Paid SEO provider APIs as a prerequisite.
-   Ads management, website builder, link outreach marketplace, full
    content publishing studio.

## 6. Data sources

-   Public website pages, robots.txt and XML sitemaps for crawl-derived
    information.
-   Google Search Console for verified property search performance.
-   GA4 only when customer authorizes it.
-   Customer-provided business context and target topics.
-   OpenAI API for language reasoning and content assistance.
-   Optional third-party SEO providers behind provider-neutral adapters,
    disabled by default.

Do not scrape Google Search result pages in a way that violates
applicable terms or access restrictions. Any future SERP data collection
must undergo legal, reliability and cost review.

## 7. Autonomy model

-   **Read-only:** URL submission can initiate a limited public-site
    crawl.
-   **Verified monitoring:** Domain verification enables recurring
    monitoring and property-specific configuration.
-   **Authorized writing:** A CMS/deployment connector with scoped
    permissions is required before publishing changes.
-   **Risk 0:** Analysis only.
-   **Risk 1:** Narrow, reversible, low-risk changes may be
    auto-executed if customer policy explicitly enables them.
-   **Risk 2:** Material content, canonical, redirect, indexability or
    template changes require approval by default.
-   **Risk 3:** Destructive, broad or high-impact actions are blocked or
    require explicit human approval and a tested rollback path.

## 8. SEO coverage

Initial rule groups: - HTTP status, redirects, redirect chains and
broken links. - Indexability directives, meta robots and robots.txt
observations. - Canonical presence and consistency. - Sitemap presence
and URL inclusion. - Title and meta description presence/length
heuristics. - Heading structure and duplicate/missing metadata. -
Structured data syntax/validation signals. - Internal-link discovery and
orphan-page candidates. - Mobile/HTML accessibility signals where
reliably measurable. - Page performance signals using appropriate
lab/field data sources when available.

The product must label heuristics separately from confirmed errors and
show evidence for every finding.

## 9. Success metrics

Product metrics: - Time from URL submission to first useful baseline. -
Crawl success and page discovery rate. - Finding precision and
false-positive rate. - Percentage of proposed changes accepted. -
Post-change validation pass rate. - Mean time to detect regression. - AI
cost and infrastructure cost per monitored site. - Weekly active sites
and retention.

SEO outcome metrics: - Search Console clicks, impressions, CTR and
average position trends. - Landing-page query coverage and page-level
trends. - Conversion metrics only when GA4 or another authorized source
is connected.

SEO outcome metrics are observational and should not be attributed to a
RankPilot change without evidence and suitable caveats.

## 10. Commercial hypothesis

Pricing hypotheses only; validate with pilots: - Solo: \$29/month. -
Business: \$79/month. - Pro: \$149/month. - Agency: \$299/month. -
Agency Plus: \$599/month.

Meter plans by monitored sites, crawl/page allowance, execution volume,
history and collaboration. Do not price around AI token credits as the
primary value metric. Apply fair-use limits and overage controls.

## 11. Acceptance criteria for MVP

-   A user can add an owned website and complete verification.
-   A controlled crawl discovers URLs and produces evidence-backed
    findings.
-   Technical rules are reproducible and tested.
-   Search Console can be connected and metrics displayed with
    date/latency context.
-   AI proposals conform to a strict schema and cite the evidence they
    rely on.
-   No website write occurs without valid connector authorization and
    policy permission.
-   Every executed change has before/after records and validation
    results.
-   Customer can pause automation, revoke access and delete the
    workspace.
-   Usage and cost are attributable per tenant/site.

## 12. Related specifications

See SYSTEM_ARCHITECTURE.md, DATABASE_SCHEMA.md, API_SPECIFICATION.md,
AI_AGENT_SPECIFICATION.md, SEO_AUTOMATION_ENGINE.md,
WEBSITE_CONNECTORS.md, SECURITY_SPECIFICATION.md, QA_TEST_STRATEGY.md,
MVP_IMPLEMENTATION_ROADMAP.md and DEVELOPMENT_TASKS.md.
