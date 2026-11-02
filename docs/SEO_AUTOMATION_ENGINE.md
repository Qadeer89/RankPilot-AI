# RankPilot AI --- SEO Automation Engine

## 1. Purpose

The engine manages the loop from evidence-backed SEO opportunity to
authorized change and verified outcome. It should never publish changes
merely to appear active.

## 2. Opportunity lifecycle

Discovered → evidence collected → deduplicated → scored → AI
explanation/proposal → policy evaluation → approval or auto-eligible →
execution → validation → monitored outcome → closed/reopened.

Each transition is timestamped and auditable.

## 3. Opportunity scoring

Use a transparent score based on: - Potential impact (heuristic, not
promise). - Confidence in evidence. - Search Console opportunity
signals, if connected. - Effort and implementation complexity. - Risk
and reversibility. - Customer priority and page importance.

Show score components to avoid opaque AI rankings.

## 4. Risk tiers

-   **Tier 0 --- analysis:** no website changes.
-   **Tier 1 --- low-risk bounded change:** narrow metadata or similarly
    reversible changes; auto-execution only if customer explicitly
    enables it and connector supports safe verification.
-   **Tier 2 --- material change:** substantial content edits,
    internal-link changes at scale, canonical changes, redirects or
    indexability changes; approval required by default.
-   **Tier 3 --- high impact/destructive:** mass edits, template-wide
    changes, deletion, noindex/robots changes affecting many pages;
    blocked by default or explicit approval plus tested rollback.

## 5. Execution protocol

1.  Confirm domain ownership and connector authorization.
2.  Validate connector scopes and current website state.
3.  Check policy, risk tier, crawl budget and idempotency.
4.  Capture before-state and create an audit record.
5.  Obtain approval when required.
6.  Execute one bounded operation.
7.  Fetch the affected page again.
8.  Run deterministic validation rules.
9.  Store after-state and validation evidence.
10. Roll back or raise an incident if validation fails and a safe
    rollback path exists.

## 6. Daily operation

Daily jobs may: - Check site availability and key page health. - Crawl
changed/high-priority URLs. - Refresh Search Console data according to
API availability and quotas. - Re-score opportunities. - Prepare
proposals. - Execute only policy-eligible actions. - Validate previous
changes. - Send concise activity summaries.

Do not force daily content changes. A no-change day is valid.

## 7. Validation rules

After a change, verify at minimum: - Expected content/metadata is
present. - HTTP status remains acceptable. - Canonical is correct. -
Robots/indexability did not regress. - Sitemap and internal links remain
valid where relevant. - Structured data remains parseable when
affected. - No unrelated critical SEO invariant regressed.

## 8. Rollback

Rollback must be connector-specific and based on a stored before-state
or known previous deployment. Never promise rollback when the connector
cannot restore the prior state. Automatic rollback requires
corroborating failures or a narrowly defined deterministic trigger;
otherwise pause and request approval.

## 9. Operational controls

-   Global and per-site pause.
-   Per-tenant daily action and AI budgets.
-   Maximum concurrent crawls.
-   Page and request budgets.
-   Retry ceilings and dead-letter queue.
-   Idempotency keys.
-   Audit log for every action.
-   Emergency kill switch.
