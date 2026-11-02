# RankPilot AI v1.3 — Custom Website Write & Autonomous Execution Addendum

**Document type:** Implementation requirements addendum
**Applies to:** RankPilot AI v1.3 Complete Implementation Requirements
**Status:** Proposed implementation scope for controlled founder pilot
**First pilot website:** Gul'sRehab (`gulsrehab.com`)

## 1. Executive decision

Custom websites must not remain permanently read-only. RankPilot's product promise is an autonomous SEO growth platform that discovers SEO issues, proposes fixes, implements authorized changes, validates the result, monitors for regressions, and records every action.

This addendum extends the existing v1.3 requirements; it does not replace them. Existing v1.3 security, governance, QA, deployment, and release requirements continue to apply.

**Decision:** Custom-site write capability becomes a core product capability, delivered through controlled connectors and staged autonomy—not unrestricted direct production editing.

## 2. Scope

### In scope
- CMS/framework-independent execution engine.
- Sanity CMS connector for mapped content and SEO-field updates.
- GitHub connector for code changes through branches and pull requests.
- Structured change proposals, approval policies, validation, audit history, idempotency, and rollback/recovery.
- Founder-pilot workflow for Gul'sRehab's Next.js + Sanity website.

### Not in the first release
- Arbitrary production shell/SSH access.
- Direct production file edits.
- Automatic merging of every pull request.
- Unreviewed URL, redirect, robots, canonical, or large-scale content changes.
- Guaranteed ranking, traffic, or lead improvements.
- Supporting every CMS/framework before the first connector pair is proven.

## 3. Target architecture

```text
Website + Search Console
        |
        v
Crawler + SEO Rules + Performance Analysis
        |
        v
Opportunity & Risk Engine
        |
        v
Fix Planner (typed change proposal)
        |
        v
Policy / Approval Gate
        |
        v
Connector Execution Layer
   |                 |
   v                 v
Sanity Connector   GitHub Connector
   |                 |
   v                 v
Content patch      Branch + commit + Pull Request
   |                 |
   +--------+--------+
            |
            v
Validation Pipeline
            |
            v
Preview / Human Approval / Deployment
            |
            v
Post-deployment Crawl + Monitoring
            |
            v
Audit Log + Recovery / Rollback
```

### Architectural principles
- The execution engine is CMS/framework-independent.
- Each connector explicitly declares its capabilities; unsupported operations must be rejected.
- The planner produces typed, schema-validated proposals. It must never execute arbitrary model-generated code or commands.
- Every write passes authorization, policy, approval, and validation checks.
- Prefer narrowly scoped, reversible changes.
- Credentials remain server-side and are never exposed to the model or browser.
- An API success response is not proof that a change is live or correct.
- Store before-state, intended after-state, actor, approval, timestamps, result, and validation evidence.
- Writes must be idempotent and safe to retry.

## 4. Connector strategy

### 4.1 Sanity CMS — founder-pilot content integration

Purpose: read and update explicitly mapped content documents and SEO fields in the Gul'sRehab Sanity dataset.

Initial candidate operations, subject to actual schema discovery:
- Read document by ID and document type.
- Read mapped title, description, slug, headings/content fields, image references and alt-text fields where present.
- Update mapped SEO title and meta description.
- Update mapped image alt-text fields where supported.
- Update explicitly mapped content fields for approved improvements.
- Create a draft/versioned change where the configured Sanity workflow supports it.
- Read the document back and verify persisted values.

Constraints:
- Discover actual Sanity schema field names; do not assume them.
- Patch only intended fields; do not replace entire documents unnecessarily.
- Preserve IDs, references, localization, arrays, rich-text structures and editorial data.
- Do not change slugs or publish automatically in the initial pilot.
- Use least-privilege credentials.
- Keep tokens encrypted/server-side; never send them to the browser or LLM.
- Support dry-run and human approval before writes.
- Record the original revision and detect concurrent edits.
- If a document changed since planning, stop and re-read/re-plan rather than overwrite newer work.

### 4.2 GitHub — code changes through pull requests

Purpose: prepare code-level SEO changes for custom Next.js sites without directly editing production.

Initial operations:
- Read repository metadata and permitted files.
- Inspect routes, metadata configuration, sitemap, robots directives, structured data and internal-link components.
- Create a dedicated branch.
- Apply bounded, allowlisted file changes.
- Commit with descriptive messages.
- Open a pull request containing rationale, affected files, expected SEO effect, risk, validation results and recovery guidance.
- Read CI status and PR review/merge state where permissions allow.

Initial pilot restrictions:
- No direct push to the default branch, force-push, or automatic merge.
- No arbitrary workflow-file changes.
- No secret, environment, dependency, infrastructure, authentication or payment code changes as SEO fixes.
- Require human review and merge.
- Use least-privilege GitHub App permissions or equivalent.
- Treat repository content, issues, PR comments and external page content as untrusted input.

### 4.3 Connector capability registry

Each connector declares exact operations and recovery support. Example:

```json
{
  "connector": "sanity",
  "capabilities": [
    "read_document",
    "patch_seo_metadata",
    "patch_alt_text",
    "patch_mapped_content_fields",
    "read_back_document"
  ],
  "supports_draft": true,
  "supports_rollback": "revision_or_compensating_patch"
}
```

Backend enforcement is mandatory. The UI and planner must not offer unsupported operations.

## 5. Structured change proposal

Every proposed change uses a typed, validated contract containing at least:
- `change_id`, `site_id`, `target_system`, `target_resource`
- `change_type`, `field_or_file`
- `before_value` or before-state reference
- `proposed_value` or patch reference
- `reason`, `source_evidence`, `expected_benefit`
- `confidence`, `risk_tier`, `reversibility`
- `requires_approval`, `policy_version`, `status`
- `created_by`, `approved_by`, `created_at`, `executed_at`
- `validation_result`, `rollback_reference`

Validation requirements:
- Reject unknown change types and target fields.
- Enforce payload and content-size limits.
- Validate URLs, HTML, JSON-LD and rich-text structures.
- The LLM cannot provide connector IDs, permissions, credentials, arbitrary paths or executable commands.
- Bind every proposal to a site, connector, resource and policy version.
- Require evidence, a specific target, an idempotency key and expected resource revision.

## 6. Autonomy and approval policy

Configure autonomy per site and change category. A global setting must not silently grant broader permissions to all connected sites.

| Level | Capability |
|---|---|
| 0 — Read-only | Crawl, analyze, report and monitor; no writes |
| 1 — Recommend | Generate proposals; user accepts, rejects or edits |
| 2 — Prepare | After approval, create CMS draft/patch or GitHub branch/PR; no production publish/merge |
| 3 — Pre-approved low-risk | Execute only explicitly allowlisted, reversible changes under site-specific limits |
| 4 — Deployment automation | Later capability; site opt-in, passing checks, explicit deployment policy and tested recovery |

Level 3 requirements:
- Explicit opt-in per site and category.
- Daily write, page-batch and total-volume limits.
- Strict field/file allowlists.
- Pre/post validation.
- Pause on validation failure, unusual errors, conflict or policy breach.
- Notify the site owner and record every action.

### Initial pilot approval matrix

| Change category | Initial policy |
|---|---|
| SEO title / meta description | Approval required |
| Image alt text | Approval required |
| Small mapped content edit | Approval required |
| Internal links | Approval required |
| JSON-LD / structured data | Approval required |
| Canonical tags | Human approval and PR review |
| Robots.txt / noindex | Human approval and PR review |
| Redirects / URL / slug changes | Human approval; excluded from automatic execution |
| Sitemap generation logic | Human approval and PR review |
| Bulk changes | Separate batch approval and limits |
| Production deployment | Human-controlled |

## 7. Validation pipeline

### Before execution
- Re-fetch the target and confirm its revision is unchanged.
- Verify connector authorization and capability.
- Validate patch against schema and policy.
- Capture before-state and crawl evidence.
- Check for conflicting pending changes.
- Run dry-run and show a human-readable diff.

### After Sanity write
- Read the document back.
- Confirm only intended fields changed.
- Confirm references, localization and rich-text structures remain valid.
- Verify the rendered page in preview/staging.
- Crawl the affected URL and validate relevant SEO output.
- Do not report production success until the live page is fetched and verified.

### After GitHub PR creation
- Verify branch, commit and PR.
- Run configured lint, type-check, unit and build tests.
- Run preview checks where available.
- Crawl preview URL and compare expected SEO output.
- Require human review and merge in the initial pilot.
- After deployment, crawl the live URL again.

### On validation failure
- Mark failed or needs-review; never report success.
- Stop dependent changes in the batch.
- Do not blindly retry non-idempotent operations.
- Preserve logs and before-state.
- Notify the site owner.
- Offer rollback/recovery only where supported.
- Pause Level 3 execution for the affected site until reviewed.

## 8. Rollback, recovery and audit history

- Store a before-state snapshot or immutable reference for every write.
- Sanity: use revision history or a compensating patch after checking the current revision.
- GitHub: revert the relevant commit or close/revert the PR; do not rewrite shared history.
- Rollback must be authorized, logged and validated.
- Never promise rollback where the external system cannot guarantee it.
- Provide a per-site timeline filterable by URL, connector, change type, actor and status.
- Record successful and failed attempts.

Suggested states:

`proposed → awaiting_approval → approved → queued → executing → validation_pending → validated → deployed`

Other states: `rejected`, `cancelled`, `conflict`, `failed`, `needs_review`, `rolled_back`.

Enforce state transitions server-side.

## 9. Security and reliability

- Encrypt OAuth tokens/API keys at rest and redact secrets from logs, prompts, traces and errors.
- Use least-privilege credentials; document scopes and support rotation/revocation.
- Verify webhook signatures where applicable.
- Protect crawlers and preview fetchers against SSRF, including private/loopback/link-local/metadata IPs and DNS/redirect re-checks.
- Apply per-host request limits, redirect-hop limits, response-size limits and timeouts.
- Treat CMS content, crawled HTML, repository files and PR comments as untrusted; defend against prompt injection.
- Strictly allowlist writable fields, file paths and change types.
- Use optimistic concurrency to prevent overwriting user edits.
- Enforce idempotency, rate limits, quotas and bounded retries.
- Add a site-level kill switch that immediately blocks new writes.
- Separate read, propose, approve, execute, publish and rollback permissions.
- Log actor, site, target, action, policy, approval, timestamps, result and validation evidence.
- Never place secrets in source control or client-side configuration.

## 10. Gul'sRehab founder-pilot plan

Gul'sRehab is the first real-world validation site because its known frontend stack is Next.js/React/TypeScript with Sanity CMS. Confirm the current production architecture, repository, Sanity project/dataset, deployment provider and Search Console property before connecting.

### Phase A — Baseline
- Verify domain ownership and HTTPS.
- Crawl public pages and establish technical SEO baseline.
- Map important routes to CMS documents or code-owned pages.
- Connect Google Search Console.
- Record impressions, clicks, CTR, average position and indexing signals.
- Identify which page fields are owned by Sanity versus code.

### Phase B — Sanity content execution
- Discover actual schemas and field mappings.
- Connect least-privilege credentials.
- Test read and read-back.
- Implement dry-run diffs.
- Approve and apply one low-risk metadata change on a staging/test document.
- Verify rendered page and crawl output.
- Test conflict handling and recovery before scaling.

### Phase C — GitHub code execution
- Connect the correct repository with least-privilege permissions.
- Identify Next.js routing and metadata patterns.
- Generate a branch and PR for one bounded technical SEO fix.
- Run build, lint, type-check and relevant tests.
- Verify preview output and SEO tags.
- Human reviews and merges.
- Verify the live site after deployment.

### Phase D — Controlled autonomy
- Enable only selected low-risk categories.
- Start with one or a few pages, not site-wide bulk changes.
- Set daily write limits and approval thresholds.
- Monitor validation failures, regressions and reversals.
- Expand only after repeated successful pilot runs.

### Pilot success metrics
Do not measure success only by ranking increases. Track:
- Correct issue-detection rate.
- Correct proposed-fix rate.
- Successful write and validation rate.
- Regression and rollback rate.
- Time from discovery to verified fix.
- Manual steps saved.
- Search Console impressions, clicks and CTR over an appropriate period.
- Organic leads/conversions where tracking is available.

## 11. Implementation work register

Map these items to existing v1.3 work IDs where equivalents exist; avoid duplicate tickets.

| ID | Priority | Work item | Acceptance evidence |
|---|---|---|---|
| CW-001 | P0 | Connector capability interface/registry | Unsupported operations rejected by tests |
| CW-002 | P0 | Typed change proposal and state machine | Schema and transition tests |
| CW-003 | P0 | Per-site autonomy policy and approval gates | Authorization tests for every level |
| CW-004 | P0 | Site-level write kill switch | Queued/new writes blocked when disabled |
| CW-005 | P0 | Encrypted credential storage and redaction | Secret-handling tests and log inspection |
| CW-006 | P0 | Sanity schema discovery/mapping | Verified mappings for actual schemas |
| CW-007 | P0 | Sanity read and targeted patch | Read/write/read-back integration tests |
| CW-008 | P0 | Sanity revision conflict detection | Concurrent edit cannot be overwritten |
| CW-009 | P0 | Sanity dry-run diff and approval | Dry-run never writes; approval enforced |
| CW-010 | P0 | GitHub least-privilege connection | Permission and token-scope tests |
| CW-011 | P0 | GitHub branch, commit and PR creation | Test PR created with change metadata |
| CW-012 | P0 | Allowlist GitHub paths/change types | Protected-path negative tests |
| CW-013 | P0 | Build/lint/type-check/preview hooks | Failed check blocks promotion |
| CW-014 | P0 | Post-write/post-deploy SEO verification | Affected URL re-crawled and compared |
| CW-015 | P0 | Immutable audit/change history | Every attempt has actor, target, policy and result |
| CW-016 | P0 | Rollback/recovery workflows | Sanity compensating patch and Git revert tested |
| CW-017 | P0 | Batch limits, idempotency and bounded retries | Duplicate request cannot duplicate write |
| CW-018 | P0 | Prompt-injection defenses for connector data | Adversarial content tests |
| CW-019 | P0 | Pause site on validation failures | Failure pauses autonomous writes |
| CW-020 | P1 | Deployment-provider integration | Preview/deployment status verified |
| CW-021 | P1 | Low-risk allowlist for Level 3 | Only opted-in categories auto-execute |
| CW-022 | P1 | Execution dashboard and timeline | Proposal-to-validation lifecycle visible |
| CW-023 | P1 | Gul'sRehab route-to-Sanity mapping | Target routes have explicit ownership mapping |
| CW-024 | P1 | Pilot metrics and before/after report | Reproducible baseline and pilot report |

## 12. Required tests

At minimum:
- Missing, expired, revoked and insufficient-scope credentials.
- Unsupported connector operation.
- Cross-tenant/site access attempts.
- Unauthorized approval or execution.
- Dry-run never writes.
- Stale revision and concurrent CMS edit.
- Duplicate/idempotent execution request.
- Malformed or oversized CMS patch.
- Protected GitHub file path.
- PR creation and partial failures.
- CI/build/preview failure.
- Live SEO validation mismatch.
- Rollback when the resource has since changed.
- Kill switch during queued work.
- Prompt injection in CMS, HTML, repository files and PR comments.
- Rate-limit responses and bounded retries.
- Secret redaction in logs and errors.

## 13. Release gates

Do not enable production write capability on Gul'sRehab until:
1. Existing v1.3 P0 security and tenant-isolation gates pass.
2. Connector credentials are least-privilege and encrypted.
3. Change schema and server-side state machine are enforced.
4. Dry-run and human approval are proven.
5. Sanity write/read-back and revision-conflict tests pass.
6. GitHub branch/PR and protected-path tests pass.
7. Build and preview validation can block unsafe changes.
8. Post-change crawl verifies rendered output.
9. Audit history and recovery procedures are tested.
10. Site-level kill switch works.
11. Backup/recovery responsibilities are documented.
12. Founder approves the first production write after staging rehearsal.

Until then, use read-only analysis and staging/test resources. Connector code existing is not proof of production readiness.

## 14. Repository documentation updates

- Keep the existing v1.3 complete requirements document.
- Add this addendum under `docs/`, e.g. `RANKPILOT_V1_3_CUSTOM_WEBSITE_WRITE_EXECUTION_ADDENDUM.md`.
- Update `docs/README.md` or documentation index to link both.
- Update P0/P1 work register without duplicating existing tasks.
- Update architecture diagrams, API contracts, database schema and environment documentation as implementation evolves.
- Record unresolved decisions explicitly. Do not invent Gul'sRehab schema fields, repository paths, deployment provider or credential scopes.
- Preserve cross-file links and run Markdown/link checks.

## 15. Final product decision

RankPilot must evolve from an SEO detection-and-recommendation tool into a controlled SEO execution platform.

For the first custom-site pilot:
- Sanity handles mapped content and metadata writes.
- GitHub handles code changes through branches and pull requests.
- CI/preview and crawler validation verify changes.
- Human approval controls production changes.
- Autonomy expands only after measurable reliability.

This gives Gul'sRehab a practical path from SEO diagnosis to verified implementation while creating a reusable architecture for future RankPilot customers with custom websites.
