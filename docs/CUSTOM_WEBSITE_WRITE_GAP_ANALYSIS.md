# Custom Website Write & Autonomous Execution — Gap Analysis (CW addendum vs. repo as of 2026-11-02)

**Purpose:** Ground the [Custom Website Write & Autonomous Execution Addendum](RANKPILOT_V1_3_CUSTOM_WEBSITE_WRITE_EXECUTION_ADDENDUM.md) (CW-001..CW-024) against the code that actually exists in this repository today, so the work register does not duplicate what is already built and does not claim anything is done that isn't test-verified.

**Status:** Analysis only. No CW-series code has been written yet. Nothing below should be read as "implemented."

---

## 1. What the addendum asks for that the repo already has a working equivalent of

The repo's existing WordPress/Shopify/Webflow/GitHub execution path (built during the P0 round, `apps/api/app/execution/service.py`, `app/execution/policy.py`, `app/execution/connections.py`) is architecturally very close to what the addendum describes — proposal → approval → execute → validate → before/after record → rollback. This is good news: most CW items are **extensions of an existing, tested pattern**, not new systems.

| Addendum concept | Existing repo equivalent | Verdict |
|---|---|---|
| Typed change proposal (§5) | `SEOTask.proposed_change_json` + `risk_tier` + `idempotency_key` (`app/models/seo_task.py`) | Partial — same role, narrower schema (no `confidence`, `reversibility`, `policy_version`, `expected_resource_revision`) |
| Policy/approval gate (§6) | `app/execution/policy.py` (`is_risk_tier_blocked`, `requires_approval`) + `Approval` model | Partial — single `risk_tier` int, not the category-based matrix (§6 table) or Levels 0–4 |
| Connector execution layer (§3) | `GENERIC_CONNECTOR_MODULES` dict in `service.py` dispatching to `find_target`/`get_current_value`/`apply_change`/`validate_change`/`rollback` per connector module | Equivalent shape — but it's an implicit Python dict, not a declared capability registry (§4.3); an unsupported operation currently fails with a raw `KeyError`/`ValueError`, not a clean rejection |
| Before/after audit record (§5, §8) | `ChangeRecord` (`before_state_json`/`after_state_json`/`actor_type`/`validation_status`) | Done for the 4 existing connectors; needs a Sanity-shaped before/after payload |
| Rollback (§8) | `RollbackRecord` + `rollback_change()`, proven for GitHub/Shopify in tests (RP13-017/018) | Equivalent shape — needs a Sanity `rollback()` implementation |
| Encrypted credential storage (§9) | `app/core/encryption.py` (Fernet) used identically by all 4 connectors in `execution/connections.py` | Done as a pattern — just needs to be applied to Sanity, no new design work |
| Website-level pause (§9 kill switch) | `Website.status` (`active`/`paused`/`deleted`); `execute_task()` already raises `ExecutionBlocked` when `status != active`; `crawls.py` already blocks new crawls on pause | Partial — see gap below: pause is all-or-nothing, not write-specific |
| GitHub branch/commit/PR (§4.2) | `app/connectors/github_pr.py` — already creates branch, commits, opens PR, closes PR on rollback, least-privilege PAT scoped to one repo | Done for the existing `set_title`/`set_meta_description` operations |

**Implication for the task sequence:** CW-001, CW-002, CW-003, CW-004, CW-005, CW-010, CW-011, CW-015, CW-016 should be scoped as **extensions to existing files** (`execution/service.py`, `execution/policy.py`, `execution/connections.py`, `models/seo_task.py`, `models/change_record.py`), not new modules. Writing them as new parallel systems would violate the addendum's own instruction not to duplicate existing tasks.

---

## 2. Real gaps — nothing in the repo does this today

These are genuine new work, not extensions:

1. **No Sanity connector at all.** Confirmed by repo-wide search — zero references to "sanity" outside third-party library source in `.venv`. CW-006 through CW-009 are fully greenfield.
2. **No dry-run mode anywhere in the execution path.** `execute_task()` goes straight from "approved" to a live write. The addendum requires dry-run-with-diff *before* approval, for every connector, not just Sanity (§6 Level 2, §7 "Before execution"). This is a cross-cutting gap in `execution/service.py`, not a Sanity-only feature — building it only for Sanity would leave WordPress/Shopify/Webflow/GitHub non-compliant with the addendum's own validation pipeline.
3. **No optimistic-concurrency / stale-revision check.** `execute_task()` re-fetches `before_value` at execution time but never compares it against what the proposal was planned against. If the underlying resource changed between proposal and execution, the current code silently overwrites it. The addendum calls this out explicitly in §4.1, §7, and the required-tests list (§12: "Stale revision and concurrent CMS edit"). This needs to become a generic connector-interface addition (e.g., `get_current_revision()` + a revision field on `SEOTask`/`ChangeRecord`), with Sanity as the first real consumer.
4. **No declared connector capability registry.** `GENERIC_CONNECTOR_MODULES` is a dispatch table, not a declared, inspectable list of operations per connector (§4.3's JSON example). Nothing currently stops the API/UI from *offering* an operation a connector doesn't support — it only fails late, inside execution.
5. **Operation vocabulary is narrower than the addendum wants.** Today every connector only implements `set_title` / `set_meta_description` (confirmed by reading `shopify.py`, `webflow.py`, `github_pr.py`). The addendum's Sanity scope additionally wants alt-text and mapped-content-field patches (§4.1), and its approval matrix (§6) separately lists JSON-LD, canonical, robots, internal links, redirects as categories — none of which have an `operation` value anywhere in the codebase yet.
6. **No GitHub CI/build/lint hook integration.** `github_pr.py`'s own docstring is explicit that its "validation" only confirms the PR exists, is open, and the branch content matches — it does **not** read CI status or run build/lint/type-check. CW-013 and the "Read CI status" bullet in §4.2 are fully new work.
7. **No protected-path allowlist with negative tests.** `github_pr.py` only ever touches the one file matched by its `_candidate_paths()` convention, so it's safe by construction for the one operation it supports — but there is no explicit, testable allowlist/denylist (e.g., rejecting `.github/workflows/*`, `.env*`, `package.json` dependency edits) the way CW-012 and §12's "Protected GitHub file path" test require. This matters once the operation vocabulary in gap #5 expands beyond title/meta.
8. **No write-specific kill switch.** `Website.status = paused` already blocks writes (good), but it also blocks crawling (`crawls.py`), so there's no way today to keep monitoring a site while specifically blocking writes — which is what CW-004 and §9 ask for. This needs either a new field (e.g., `writes_enabled: bool` on `Website` or inside `automation_policy`) or an explicit decision to keep pause as one combined switch (a decision worth recording rather than assuming).
9. **No category-based approval matrix or autonomy Levels 0–4.** `execution/policy.py` has one `risk_tier` int (0–3) and one `automation_policy["auto_execute_risk_tier_1"]` boolean. The addendum's §6 table (SEO title/meta/alt-text/links/JSON-LD/canonical/robots/redirects/sitemap/bulk/deployment, each with its own policy) and the 5-level autonomy scale are materially richer and not present.
10. **No execution/proposal dashboard timeline.** CW-022 — need to verify what the P1 frontend work actually built for task/approval review before assuming this is fully missing; flagged as "needs verification," not assumed done or missing.
11. **No prompt-injection-specific tests for connector-sourced content.** CW-018 and the required-tests list ask for adversarial-content tests (CMS content, crawled HTML, repo files, PR comments fed back into AI prompts). The AI prompt-construction code (`app/ai/`) has not been audited against this requirement as part of this analysis — flagged for a dedicated audit pass before claiming it's handled either way.
12. **Request-level idempotency vs. task-level idempotency.** `create_tasks_from_proposal()`'s idempotency key prevents duplicate *tasks*, but `execute_task()` itself has no separate idempotency key guarding a duplicate *execution request* against an already-executing task beyond the status check (`SEOTaskStatus.executing`/`completed`). Worth a dedicated concurrent-request test per §12 ("Duplicate/idempotent execution request") before assuming the existing status check is sufficient under real concurrency (the AI-budget work earlier in this project found a real race condition hiding behind what looked like sufficient guards — same caution applies here).

---

## 3. Unresolved inputs this analysis will not invent

Per the addendum's own instruction (§14: "Do not invent Gul'sRehab schema fields, repository paths, deployment provider, or credential scopes") and item 6 of your request, the following were genuinely unknown from the RankPilot repo alone. Confirmed directly against the real `Qadeer89/gulsrehab-website` repository (cloned read-only, commit `56a0d4d`) on 2026-11-02:

| Input | Status |
|---|---|
| GitHub repository | **Confirmed:** `Qadeer89/gulsrehab-website` |
| Deployment provider | **Confirmed:** PM2 self-hosted (founder-stated) |
| Sanity project ID | **Confirmed:** `6hfrrnn7` — committed in `.env.example` as `NEXT_PUBLIC_SANITY_PROJECT_ID`; not a secret (the `NEXT_PUBLIC_` prefix means it already ships to the browser) |
| Sanity dataset | **Confirmed:** `production` — `.env.example`'s `NEXT_PUBLIC_SANITY_DATASET` |
| Sanity schema (document types + fields) | **Confirmed by reading `src/sanity/schemaTypes/*.ts` directly** — see table below |
| CI configured in the repo | **Confirmed absent:** no `.github/workflows` directory exists in the repo |
| Sanity API token (actual secret, scoped) | **Still needed** — cannot exist in source by design; founder must generate one in `manage.sanity.io` → project `6hfrrnn7` → API → Tokens, least-privilege (Editor, not Admin), for RankPilot specifically |
| Staging/test environment for Gul'sRehab | **Still needed** — not yet confirmed whether PM2 serves a separate staging instance or production only |

### Confirmed Sanity schema (`src/sanity/schemaTypes/`)

The Sanity dataset governs **only three document types** — `blog`, `blogCategory`, `blogTag` — plus a near-empty `service` reference type. This is a materially smaller write surface than the addendum assumed, and it changes the pilot's scope:

| Document type | Fields relevant to RankPilot writes |
|---|---|
| `blog` (blog article) | `seoTitle` (string, ≤60), `seoDescription` (text, ≤160), `canonicalUrl` (url), `noIndex` (boolean), `openGraphImage` (image), `featuredImage.alt` (string, required), inline `image.alt` inside the `content` portable-text array, `title`, `excerpt` |
| `blogCategory`, `blogTag` | taxonomy only — no independent SEO fields observed |
| `service` | **only** `title` + `slug` — no SEO fields, no content fields in Sanity at all |

**Implication:** the repo also uses Prisma/Postgres (Neon) (`prisma/schema.prisma`, `DATABASE_URL` in `.env.example`) alongside Sanity. Service/landing pages — likely the commercially important pages — are not Sanity-managed at all; their content lives in the database and/or directly in Next.js route code under `src/app`. This means:
- **Blog-page SEO fixes** (title/meta/canonical/noindex/alt-text) → Sanity connector, CW-006..CW-009 as scoped.
- **Service-page SEO fixes** → not reachable through Sanity at all; these would need either the GitHub connector (if hardcoded in route/component code) or a **new, not-yet-scoped Prisma/Postgres write path** if they're database-driven. This needs a dedicated discovery pass against `src/app` and `prisma/schema.prisma` before Phase A's "map important routes to CMS documents or code-owned pages" step can be called complete — do not assume service pages are covered by the Sanity connector alone.

Everything else in the revised sequence below (Section 4, steps 1–15) remains buildable and testable today against the existing RankPilot execution architecture without needing the two still-open inputs (Sanity token, staging environment). Phase B (Sanity staging-document test) needs the token; Phase C/D's "preview" steps need the staging-environment answer, given PM2 self-hosted has no automatic per-PR preview like Vercel/Netlify.

---

## 4. Revised task sequence

Grouped by dependency, not by the addendum's original P0/P1 split — some "P0" items in the addendum are blocked on inputs in Section 3 and cannot be first regardless of priority label.

### Group A — Cross-cutting execution-engine foundation (blocks everything else; buildable now)

**Status: done** (commit `49803ae`, 2026-11-03) — 16 new tests, full suite 278/278 passing, `alembic check` clean.

1. ~~**Connector capability registry** (CW-001)~~ — done: each connector module declares `SUPPORTED_OPERATIONS`; `execution/service.py` exposes `get_connector_capabilities()` and `CONNECTOR_CAPABILITIES`; both `create_tasks_from_proposal()` and `execute_task()` reject an unsupported operation before touching the connector.
2. ~~**Dry-run mode**~~ — done: `execution/service.py::dry_run_task()` runs `find_target`/`get_current_value`/diff without ever calling `apply_change`, for all 4 existing connectors (WordPress's own code path and the 3 generic ones). Exposed as `POST .../tasks/{id}/dry-run`.
3. ~~**Stale-revision / optimistic-concurrency check**~~ (feeds CW-008) — done, but narrower than the addendum's full `get_current_revision()` design: `dry_run_task()` stores the live value it read as `expected_before_value` on the task; `execute_task()` re-fetches the current value before writing and blocks with "Stale revision" if it no longer matches, rather than silently overwriting a concurrent edit. This catches a *value* change, not every kind of revision/version change a richer revision ID would — acceptable for the title/meta-description operations that exist today, but worth revisiting once Sanity's native document `_rev` field is available (Group C) since that's a stronger signal than comparing a single field's value.
4. ~~**Write-specific kill switch** (CW-004)~~ — done: `Website.writes_enabled` (new column, migration `efd132153f72`), distinct from `status=paused`. `execute_task()` blocks on it; `dry_run_task()` (read-only) is unaffected, matching the addendum's "blocks new writes" (not analysis) framing. Exposed as `PUT .../writes-enabled`.
5. ~~**Category-based approval matrix + autonomy levels** (CW-003)~~ — **partially done**: `execution/policy.py` now has `OPERATION_CATEGORY` (currently just `set_title`/`set_meta_description` → `"metadata"`, since no other operations exist yet) and a tier-1 `automation_policy.auto_execute_categories` opt-in, alongside the existing blanket `auto_execute_risk_tier_1` flag. **Not done**: the full Levels 0–4 scale and the complete §6 category table (JSON-LD, canonical, robots, redirects, sitemap, bulk, deployment) — those need real operations to exist first (Group B/C), so inventing their categories now would be exactly the kind of unverified assumption this document is supposed to avoid.

### Group B — GitHub hardening (buildable now, no pilot inputs needed)

**Status: done** (2026-11-03), tests in `test_group_b_github_hardening.py` — full suite 289/289 passing.

6. ~~**Protected-path allowlist + negative tests** (CW-012)~~ — done: `github_pr.PROTECTED_PATH_PREFIXES`/`_is_protected_path()` denies `.github/`, `.env*`, `package.json`/lockfiles, `Dockerfile`, `requirements.txt`, deployment-config files, etc. Enforced twice (defense in depth): `find_target()` skips a protected candidate path before ever asking about it, and `apply_change()` independently refuses to write one even if a `target_ref` for one were ever constructed some other way.
7. ~~**CI/build/lint/type-check hook integration + block-on-fail** (CW-013)~~ — done, **with an honest limitation**: `github_pr.get_combined_status()` reads GitHub's combined-status API for the PR branch and `validate_change()` now blocks promotion (`passed = False`) on an already-reported `"failure"`. It is a single snapshot taken immediately after opening the PR, not a wait-for-CI-to-finish poll — CI has usually not started yet by that point, so `"pending"`/`"no_checks"` do not block. A true "wait for CI, then report" flow needs an async follow-up (scheduled re-check or webhook), which is **not built yet** — tracked as a known gap, not silently claimed as solved.
8. ~~**Post-deploy crawl verification for the GitHub path** (CW-014)~~ — done: new `execution/service.py::verify_github_deployment()` + `POST .../change-records/{id}/verify-deployment`, human-triggered (RankPilot has no deploy-pipeline visibility to call this automatically). Re-crawls the live `target_url` via the existing SSRF-safe `crawler.fetch.safe_fetch()` and compares against the proposed value, recording the result under `ChangeRecord.after_state_json.post_deploy_verification` without overwriting the original PR-branch `validation_status`.

### Group C — Sanity connector

**Status: done** (2026-11-03), tests in `test_sanity_connector.py` — full suite 296/296 passing at the time.

9. ~~Sanity credentials + encrypted storage~~ — done, reusing the existing `core/encryption.py` pattern exactly as the other 4 connectors do.
10. ~~Sanity schema discovery~~ — done differently than planned: rather than a runtime discovery *tool*, the real schema was read directly from the `gulsrehab-website` repo's `src/sanity/schemaTypes/*.ts` (§3 above) and the connector was built against those confirmed field names (`seoTitle`, `seoDescription` on `blog` documents). A generic runtime discovery tool for a *different* future Sanity-backed customer is still not built — only this pilot's schema is hard-coded as `FIELD_BY_OPERATION`/`DOCUMENT_TYPE` in `app/connectors/sanity.py`, which is an intentional, documented scope limit (the module docstring says so), not an oversight.
11. ~~Sanity read / targeted patch / read-back~~ — done (`find_target`/`get_current_value`/`apply_change`/`validate_change`).
12. ~~Sanity revision-conflict detection~~ — done, and **stronger than Group A step 3's generic fallback**: every patch carries `ifRevisionID` set to the document's real `_rev`, so Sanity's own mutate API (not just this platform's value comparison) rejects a write on a real concurrent edit.
13. ~~Sanity dry-run diff~~ — done, for free, via Group A's connector-agnostic `dry_run_task()`.

**Still open before this can run against real Gul'sRehab data**: the Sanity API token (§3 — must be founder-generated, cannot exist in source). Not yet exercised against the live project.

### Group D — Reliability/security cross-cutting

**Status: done** (2026-11-03) — full suite 311/311 passing.

14. ~~Request-level idempotency for `execute_task()`~~ — done, and **a real concurrency bug was found and fixed while proving it**: `with_for_update()` alone was not sufficient — SQLAlchemy's identity map returned the *already-loaded* Python object without refreshing its attributes from the lock-acquiring SELECT, so a second, blocked caller still saw the pre-lock `.status` in memory even after the first caller committed. Fixed with `.populate_existing()`. A second, unrelated bug was found by the same real-Postgres test approach: `dry_run_task()`'s original implementation mutated the `proposed_change_json` dict in place *before* reassigning it, which corrupted SQLAlchemy's own "old value" snapshot (same object, by reference) and silently skipped the UPDATE on flush -- the stale-revision check from Group A step 3 was not actually persisting its "expected" value to the database at all until this was fixed. Verified with real threads and real, separate Postgres connections in `test_execute_task_concurrency.py` (`engine` fixture, not the rollback-wrapped `db_session` fixture), the same approach the AI-budget advisory lock was proven with earlier in this project.
15. ~~Prompt-injection audit + adversarial tests~~ — done. Audit found the existing AI layer (`app/ai/{content_agent,internal_linking,qa_assistant,strategy_assistant}.py`) already had solid structural defenses: every agent's system prompt explicitly frames crawled/connector content as untrusted data, `OpportunityProposal`'s `RESPONSE_JSON_SCHEMA` already sets `additionalProperties: False` + `strict: True` for the real OpenAI call, and `validate_allowed_operations()` enforces the operation allowlist in Python too. Added `model_config = {"extra": "forbid"}` to `OpportunityProposal`/`ProposedAction`/`EvidenceRef` as defense-in-depth for any caller that parses a proposal outside the OpenAI structured-output path. 14 new tests in `test_prompt_injection_defenses.py`, including a regression guard that every agent's `SYSTEM_PROMPT` keeps its untrusted-data framing. Honest limitation: no test can prove a real LLM won't be "fooled" by injected text -- these tests prove the structural guarantees that make that question moot (an unsafe action literally can't be expressed in the schema), not model behavior itself.

### Group E — Gul'sRehab pilot execution (blocked until Section 3 is answered)
16. Confirm GitHub repo, Sanity project/dataset/token scope, deployment provider, GSC property.
17. Phase A — baseline crawl + GSC connect.
18. Phase B — Sanity staging-document test, using Groups A–C above.
19. Phase C — GitHub PR test on one bounded fix, using Groups A–B above.
20. Phase D — controlled autonomy expansion, gated by §13's release gates.

---

## 5. Release-gate status (addendum §13), honestly as of today

**Updated 2026-11-03 after Groups A–D landed** (commits `49803ae`, `ee40e1b`, `98cff9b`, and the Group D commit below). Full suite: 311/311 passing.

| Gate | Status |
|---|---|
| 1. Existing v1.3 P0 security/tenant-isolation gates pass | **Met** — RP13-001..024 completed with tests in the prior P0 round |
| 2. Connector credentials least-privilege and encrypted | **Met** for all 5 connectors including Sanity (`core/encryption.py` pattern) |
| 3. Change schema + server-side state machine enforced | **Partial, improved** — `SEOTask`/`Approval`/`ChangeRecord` transitions enforced server-side; capability registry (CW-001) and category-based tier-1 opt-in (CW-003) added; still narrower than addendum §5's full typed-proposal schema (no `confidence`/`reversibility`/`policy_version` fields) and §6's full Levels 0–4 |
| 4. Dry-run and human approval proven | **Met** — `dry_run_task()` + stale-revision conflict detection, tested for both the generic connectors and Sanity (with Sanity's native `_rev` check) |
| 5. Sanity write/read-back/revision-conflict tests pass | **Met** in test form (7 tests, `test_sanity_connector.py`) — **not yet exercised against the real live project**; the Sanity API token is still the one open input |
| 6. GitHub branch/PR + protected-path tests pass | **Met** — protected-path denylist enforced twice (find_target + apply_change), negative tests pass |
| 7. Build/preview validation blocks unsafe changes | **Partial** — CI-failure blocks promotion (CW-013); true wait-for-CI-completion (not just a post-open snapshot) is a documented, not-yet-built follow-up |
| 8. Post-change crawl verifies rendered output | **Met** — WordPress (`validate_wordpress_change`) and GitHub (`verify_github_deployment`, human-triggered post-merge) both covered; Shopify/Webflow/Sanity validate via their own live read-back in `validate_change()` |
| 9. Audit history + recovery tested | **Met** for all 5 connectors (`ChangeRecord`/`RollbackRecord`, including Sanity's compensating-patch rollback) |
| 10. Site-level kill switch works | **Met** — `Website.writes_enabled` is write-specific, distinct from crawl pause, tested including that dry-run stays available while it's off |
| 11. Backup/recovery responsibilities documented | **Met** — `ops/RUNBOOKS.md` (RP13-021) |
| 12. Founder approves first production write after staging rehearsal | **Not applicable yet** — blocked on the Sanity token and a staging rehearsal on the real Gul'sRehab pilot, not on remaining engine work |

**Conclusion: the engine-side work is essentially complete; what remains is pilot-specific, not architectural.** Every gate the platform itself controls is now Met or Partial-with-a-documented-reason; the two genuinely open items are external inputs (the Sanity token; a real staging rehearsal against live Gul'sRehab data) and one deliberately deferred async-CI-wait feature, not missing engineering. Two real concurrency/persistence bugs were found and fixed in the course of building this (Group D §14) — proof the real-Postgres/real-thread testing discipline from the prior P0 round caught something a less rigorous test would have missed here too.
