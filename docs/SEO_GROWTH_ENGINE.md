# RankPilot AI — SEO Growth Engine

How RankPilot finds growth opportunities without Semrush, Ahrefs or Moz.
Everything lives under the **Keywords** tab of a website
(`/dashboard/websites/{id}/keywords`).

## Where the data comes from

| Source | What it gives | How it is labelled |
|---|---|---|
| Google Search Console | Queries, pages, clicks, impressions, CTR, average position, country, device | Verified (your site) |
| RankPilot's own crawler | Page titles and headings used as seed keywords | Verified (your site) |
| AI keyword discovery | Related topics, intents, content-type suggestions | AI idea — not verified demand |
| Competitor analysis | Topics found on a competitor's public pages | AI idea — not verified demand |

RankPilot never shows a search volume, keyword difficulty, competition
score or CPC. It has no verified source for them, so those fields do not
exist anywhere in the product.

Average position is Search Console's aggregate, not a ranking every
searcher sees. Search Console data arrives a few days late.

## Target market

On the Overview tab, set the primary target country (two letters, e.g.
`US`), any additional countries, the language and an optional city. These
are used as context for AI keyword discovery.

The **Country** box at the top of the workspace filters Search Console
signals to one market. It takes Search Console's own three-letter code
(`usa`, `gbr`), which is different from the two-letter setting above.
With the box empty, signals cover all countries combined.

## Workspace tabs

- **Overview** — counts, target market settings, AI usage for the last 30 days.
- **First-Party Keywords** — Search Console rows with country, device and
  whether the query's landing page has been crawled.
- **AI Discovery** — "Run discovery" builds seed keywords from your own
  pages and queries, then asks AI to expand them. If the AI call fails,
  the seeds are still saved.
- **Country Analysis** — new queries in the last 14 days, queries on page
  two of results, and keyword cannibalization candidates.
- **Intent & Clusters** — keyword ideas grouped by search intent and by
  recommended content type.
- **Competitor Gaps** — add a competitor domain and click Analyze.
  RankPilot fetches up to five public pages (respecting robots.txt) and
  suggests topics the competitor covers that you do not. It never sees a
  competitor's traffic, rankings or backlinks. Up to 10 competitors per
  website.
- **Opportunities & Mapping** — all active ideas, highest confidence first.
- **Recommendations** — see below.
- **Performance** — see below.

## Growth recommendations

"Generate from current data" builds recommendations from stored data with
no AI call:

- queries on page two of results → strengthen the ranking page;
- several of your pages competing for one query → resolve cannibalization;
- a page losing clicks, impressions or position → review it;
- higher-confidence AI and competitor ideas → create new content.

Each recommendation shows its evidence, data source, priority, effort,
a qualitative expected benefit and how to check the result. None promises
a ranking or traffic outcome. Generating again updates open
recommendations and leaves approved, rejected and done ones alone.

### Applying a recommendation

1. Approve it.
2. If it says it can be applied automatically (it targets an existing
   page and a CMS connector is connected), click **Send for AI draft**.
3. It appears in the website's **Opportunities** tab. From there the
   normal flow applies: AI drafts a title/meta change, you preview and
   approve it, the CMS publishes it, RankPilot validates it, and you can
   roll it back.

A change that started as a growth recommendation always waits for your
approval, even in Autopilot mode with auto-execute switched on, and the
automatic crawl pipeline never drafts one on its own. The recommendation
becomes "done" once its change is applied and validated.

New-content, cannibalization and declining-page recommendations have no
automated change; do them by hand and click **Mark as done**.

## Performance timeline

For each change RankPilot published to a page: Search Console clicks,
impressions, CTR and average position in an equal window (7, 28 or 90
days) before and after. "No data" means Search Console had no rows for
that window; it is never shown as zero. "After-window still filling"
means the after period is not complete yet.

A before/after difference does not show the change caused it.
Seasonality, indexing delays, competitors and Google updates move the
same numbers.

## Limits and costs

- AI discovery and competitor analysis: 10 runs per website per hour.
- All AI calls count against the website's daily AI budget and the global
  kill switch.
- Platform admins can see estimated AI cost per website at
  `GET /api/v1/admin/ai-usage`.

## Not available

- Bing Webmaster Tools.
- Public search suggestions (autocomplete).
- Verified search volume from any source.
- Automated publishing of new pages or long-form content.

## Deploying

Run `alembic upgrade head`, restart the API, worker and scheduler,
rebuild the web app, then re-run a Search Console sync per website so
existing data picks up country and device.

## Gap closure and validation

### Country handling
All country values are stored as ISO 3166-1 alpha-2 upper case (`US`, `GB`, `PK`), with `ZZ` for "unknown".
`app/core/countries.py` is the only place that converts: Search Console's lower-case alpha-3 codes (`usa`) are
normalized at sync time, API inputs (`usa`, `UK`, `gb`) are normalized at the endpoint, and
`to_search_console_code` converts back for provider calls. Country names are not accepted as input, and there is
no substring matching. Migration `44533486c7d9` converts existing stored codes (unmappable values are left as-is).
`GET /reference/countries` feeds the UI dropdowns.

### Target market settings
Stored on the existing `websites` columns (no second model): `target_country`, `additional_target_countries`,
`target_language`, `target_city`, plus `target_languages_by_country` (per-market language). Edited through
`PATCH .../settings` (editor role, tenant-scoped, 400 on invalid codes). The Keyword Intelligence country
selector lists the target markets and defaults to the primary country.

### GA4 landing pages
`ga4_landing_page_metrics` stores organic-search sessions, engaged sessions and conversions per landing path,
mapped to crawled pages. The Performance tab shows them in a separate column from Search Console
clicks/impressions/position; GA4 is engagement data, never a ranking metric.

### Recommendation lifecycle
Pending, Approved, Rejected, In progress, Applied (manual only), Validation pending, Validated, Failed, Rolled back
are derived from the real task, change-record and rollback state (`app/growth/lifecycle.py`). Only
`improve_existing_page` recommendations on a connected CMS that supports title/meta changes are executable
(preview, approve, apply, CMS read-back validation, optional live-page re-fetch check at `verify-live`,
roll back). Every other type shows why it cannot be applied automatically. Nothing publishes without approval.

### Live validation
`scripts/validate_growth_engine.py` runs the real OpenAI agents (discovery, prompt-injection resistance,
insufficient data), SSRF blocking, and real competitor crawling for each `--competitor URL`. Crawling needs
outbound DNS, so run it on the VPS/staging.

### Post-change verification crawl
After a growth recommendation's change is applied (CMS read-back passed), RankPilot queues a one-URL crawl job
(`trigger = post_change`, `app/growth/recrawl.py`, Celery task `run_post_change_crawl`). It reuses the normal
crawler on just that URL: no sitemap seeding, no link discovery, no rules, no health score, and it never counts
as the site's "last crawl". The snapshot's title/meta description is compared with the applied value and stored on
the change record (`after_state_json.recrawl`: queued, running, validated, mismatch, failed, not_applicable).
A recommendation is **validated** only when the CMS read-back passed and the crawl confirmed the value. A
mismatch (for example a page cache) or a failed crawl never marks the change failed; it stays *validation pending*
with the reason, and "Re-crawl page" retries. The task waits while a full crawl of the same site is running.
Limitations: only growth-recommendation changes trigger it, and only title and meta description are compared.

### AI failure handling
Discovery and competitor analysis report `ai_status`/`ai_message` (`ok`, `skipped_no_input`, `unavailable`,
`invalid_response`, `input_too_large`, `budget_blocked`). A timeout, rate limit, provider error, malformed or
schema-violating response, a response that mentions fabricated metrics, an oversized prompt, a missing key or an
exhausted budget never produces a 500: first-party seeds and crawled competitor evidence are still saved, and the
UI says why no AI ideas were added.

### Competitor crawler behaviour
Public pages only, robots.txt per host, SSRF-safe at every redirect hop. HTTP 4xx/5xx and non-HTML responses are
reported, not treated as content; blocked pages are listed with the reason; requests are at least 1s apart
(honouring a Crawl-delay up to 10s); one retry for timeouts and 429/502/503/504; a 60s ceiling per domain;
`example.com` and `www.example.com` are treated as one site. JavaScript is **not** executed for competitor sites:
a page with no server-rendered title or headings is reported as such.

### Automated UI tests
`apps/web/e2e/` holds Playwright tests (`npm run test:e2e` in `apps/web`) for the Keyword Intelligence workspace:
country prefill and scoping, target market settings (add, remove, language, save, reload, rejected save), AI
discovery and competitor-analysis failure messages, recommendation generation (counts, "nothing to recommend",
unsupported reasons, manual completion), the full preview, approve, apply and verification-crawl flow (validated,
mismatch, failed) and the GA4 column. They drive the real Next.js app in Chromium against a scripted fake API
(`e2e/support/fakeApi.ts`), so they verify the frontend only, not the backend or any live provider.

### Google OAuth: expired connections and the production checklist
**What the code does today.** The consent request uses `access_type=offline` and `prompt=consent` (needed so Google
returns a refresh token every time) and asks for read-only scopes (`analytics.readonly` for GA4, plus the Search
Console read scope). When Google rejects a stored refresh token with `invalid_grant`, RankPilot now raises
`GoogleReauthRequired` with a plain "reconnect" message and marks that connection `error`, so scheduled syncs stop
calling Google with a dead token until the account is reconnected. Other refresh failures (5xx, network) are
treated as transient and do not disconnect anything.

**Why a connection can die.** Per Google's own help page on
[managing the app audience](https://support.google.com/cloud/answer/15549945), authorizations granted by test users
of an app whose publishing status is **Testing** expire after seven days (and the refresh token with them), and a
Testing app is capped at 100 test users. Moving the app to **In production** is the documented way to avoid that 7-day limit, but a connection can
still die for other reasons (for example the user revokes access in their Google account), which is why the
reconnect handling above exists. Google's
[production-readiness checklist](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)
is the reference to follow before publishing.

**Before publishing, check in the Cloud Console (APIs & Services, OAuth consent screen):**
1. *Data access*: confirm the exact scopes listed and how Google classifies each (non-sensitive, sensitive or
   restricted). Do not rely on this document for the classification of `analytics.readonly` or the Search Console
   scope: the sources I could find did not state it. If a scope is sensitive, Google may require app verification
   before the "unverified app" warning goes away.
2. *Branding and domains*: app name, support email, logo, home page, privacy policy and terms URLs on a domain you
   own (verified in Search Console), and the authorized redirect URIs for both integrations
   (`google_search_console` and `google_ga4`) matching production exactly.
3. *Audience*: switch from Testing to **In production**. While unverified, users see an "unverified app" screen.
4. *Existing users*: every user connected while the app was in Testing must reconnect once after publishing; their
   old refresh tokens cannot be extended. After that, the sync should stop failing with `invalid_grant`.
5. Keep read-only scopes only; adding a broader scope later forces a new consent and may trigger re-verification.

I could not verify Google's review timelines from an authoritative page; treat any number you read elsewhere as
an estimate.

### Site title templates (fix for "brand shown twice")
Many sites append their name to every page title in the page template. The crawled `<title>` includes that
suffix; the CMS title field RankPilot writes to does not. Before this fix the model saw the rendered title,
wrote a full new title with its own brand, and the template added the brand again ("X | Brand | Brand"), which
made titles longer and kept "Shorten an overlong page title" open. Now (`app/seo_rules/title_template.py`):
the template is learned from the site's own crawled titles (needs at least 3 pages sharing a trailing segment);
the model is told about it and is shown the title without it; and, whatever the model writes, a brand segment
the template already adds is stripped from `set_title` values in code. Verification (re-crawl, live check,
`scripts/check_applied_changes.py`) accepts the applied value followed by the template suffix, and flags a
doubled brand. Titles already damaged on live sites are not rewritten automatically.
