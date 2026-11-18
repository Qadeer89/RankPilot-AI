# Growth Engine and History: delivery report (H1-H9)

This lists what was built, how it was tested, and what has **not** been verified. Nothing here is claimed production-ready beyond what the tests below show.

## What exists now

| Area | What it does | Where |
|---|---|---|
| Immutable history | Baseline + automatic snapshots (database trigger blocks edits), per-crawl issue lists, Google daily totals, activity timeline, recommendation lifecycle log, keep-forever retention | `app/history/*`, migration `7e2cd403faa5` |
| History & Progress UI | Before/after, Google period comparison, charts, timeline, page history | `/dashboard/websites/[id]/history` |
| Customer progress report | Printable report from stored history only; Google figures only when Google data exists; fixed limitations section | `GET .../history/report`, `/dashboard/websites/[id]/report` |
| Business profile | Owner-confirmed profile; AI suggestions are separate, labelled, and offerings the site text does not support are dropped | `app/ai/business_profile.py`, migration `3892b3011a3d` |
| Growth journey | Adapts to analysing / baseline / connected; shows "Not available" with the reason instead of invented numbers | `app/growth/journey.py` |
| Unified recommendations | One list over crawl opportunities and growth recommendations; "critical" only when a critical finding exists | `app/growth/unified.py` |
| First-30-days plan | Built from real findings and connections; each item states its basis; scaled to site size; no guarantee | `app/growth/action_plan.py` |
| Shopify catalog SEO | Read-only product/collection sync, 8 deterministic checks, snapshots kept per sync | `app/shopify_seo/catalog.py` |
| Shopify AI proposals | AI draft of SEO title/meta from the product's own facts; numbers, promises, superlatives, links and unsupported claims are rejected before anything is stored; approve / edit / apply / read-back verify / undo; honours the website write kill switch | `app/ai/shopify_optimizer.py`, `app/shopify_seo/proposals.py`, migration `f3c93aa152ee` |

## Test evidence (this environment)
- Backend: full suite green (last full run 1319 passed before the report tests; report tests add 4, all passing).
- UI: 73 Playwright tests passed against a fake API.
- Lint/type checks: `tsc` and `eslint` clean for the web app.

## NOT verified
- **Shopify has only been tested against a fake store.** No real store or Admin API token was available. The REST shapes follow the documented Admin API (version pinned in `connectors/shopify.py`, currently `2024-01`, which Shopify retires over time). Run the sync against a development store before relying on it. Per-product SEO lookups are capped at 300 per sync.
- **Shopify collections are analysed but not yet optimised by AI** (no collection proposals). Products only.
- No content-growth-engine upgrade (outline / page type / internal links) was built in this round; the existing growth recommendation and content agents are unchanged.
- No real Google data: history/report behaviour with Search Console and Analytics is tested with seeded rows only.
- Page identity across URL moves is not tracked (a moved page appears as a new page).
- The 30-day plan and journey cannot say whether rankings improved; they report work and data, and the report explicitly says rankings are not guaranteed.
- Scenario tests A-F from the master prompt were not written as separate end-to-end scenarios; their behaviours are covered by the unit/API tests above (new project with no Google data, connected project, Shopify store, tenant isolation, approval gate, failed apply).

## Deploy notes
```
git pull
cd apps/api && alembic upgrade head      # ... -> 3892b3011a3d -> f3c93aa152ee
cd ../web && npm run build
pm2 restart rankpilot-api rankpilot-worker rankpilot-scheduler rankpilot-web
```
Retention now keeps history by default (no deletion unless explicitly configured).

## Where customers find things
Project page tabs: **Growth Plan**, **Shopify SEO**, **History & Progress** (with the link to the printable report).
