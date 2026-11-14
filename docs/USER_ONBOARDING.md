# RankPilot AI — User Onboarding

How a new customer goes from signing up to a site that monitors and
improves itself. Matches the master roadmap's "Final Product Acceptance
Criteria" end-to-end workflow.

## 1. Register and create an organization

`POST /api/v1/auth/register` with email, password, and an organization
name. The registering user becomes that organization's `owner` — the
only role that can rotate a deploy webhook secret or change billing-
adjacent settings; `admin` can change most website settings; `editor`
can trigger crawls and manage connectors; `viewer` is read-only.

## 2. Add a website

`POST /api/v1/organizations/{org_id}/websites` with the site's URL. The
URL is validated against SSRF risks before anything is stored (private
IPs, cloud metadata endpoints, and similar are rejected outright).

## 3. Verify domain ownership

Before RankPilot will crawl or write to a site, prove you control it:
`POST .../websites/{id}/verify/instructions` returns a token and a file
path to publish it at; `POST .../websites/{id}/verify/confirm` checks it.
Verification attempts are rate-limited and tokens expire.

## 4. Choose an automation mode

Before the first crawl, decide how hands-off you want this site to be
(`PATCH .../websites/{id}/settings`, `automation_mode`):

- **Audit** — detect and report only. No AI drafting happens, nothing is
  ever written to the site. Safe default for a new or sensitive site.
- **Copilot** — AI drafts fixes automatically after each crawl, but every
  one always waits for your approval (Tasks tab) before it executes.
- **Autopilot** — low-risk fixes you've opted into (by category or the
  blanket tier-1 toggle) auto-execute and self-validate; anything else
  still waits for approval.

Everything below works under any mode — Audit just means the "AI
proposal" and "execute" steps in step 8 never happen automatically.

## 5. Connect a content platform (optional, needed for any automated write)

Under the website's "Integrations" tab: WordPress (Application Password),
Shopify, Webflow, Sanity, or a GitHub repo for a custom-coded site. A
site with no connector connected can still be crawled, scored, and
monitored — findings and opportunities still surface — but nothing can
be written to it.

## 6. Connect Google Search Console / GA4 (optional)

Also under "Integrations". Unlocks real search-performance data (clicks,
impressions, position trends, keyword cannibalization) and Google's own
indexing view (coverage state, the canonical Google actually chose) —
without either, those dashboard sections simply stay empty, never
fabricated.

## 7. Run the first crawl

`POST .../websites/{id}/crawls`, or just wait for the scheduled one
(`crawl_frequency_hours` in Settings, default daily). The crawl discovers
pages, fetches each one (with selective headless-browser rendering for
JS-heavy pages), and the deterministic rule engine evaluates every page
against ~40 rule codes — never an AI judgment call on whether something
is actually wrong.

## 8. Review the SEO Health Score and findings

The Overview tab shows the health score (technical/on-page/content/
performance, each `null` until it has real data, never a fabricated
number) and its trend across crawls. The Findings tab lists every open
issue with its evidence. The Pages tab has a full per-page report:
snapshot, images, performance, Google's indexing view, and that page's
own fix history.

## 9. Review and act on opportunities

The Opportunities tab lists AI-drafted fixes for findings that have one
(title/meta rewrites, missing alt text, canonical/schema fixes). In
Copilot or Autopilot mode, these already exist as Tasks; in Audit mode,
you'd request a proposal manually. Approve, reject, or (once executed)
roll back a task from the Tasks tab — every executed write keeps
before/after evidence and a validation result.

## 10. Set up notifications (optional)

Organization settings: a Slack incoming webhook URL. Per website
(Settings): toggle notifications for SEO regressions and automation
summaries independently. Unconfigured, nothing breaks — notifications
are simply recorded as not sent.

## 11. Set up a deploy webhook (optional)

If your CMS or CI can call an HTTP endpoint on deploy: Settings →
"Deploy webhook" → generate a secret, then have your pipeline
`POST /api/v1/websites/{id}/webhooks/deploy` with that secret in the
`X-RankPilot-Webhook-Secret` header to trigger an immediate re-crawl
instead of waiting for the next scheduled one.

## 12. Ongoing monitoring

From here it runs on its own: scheduled crawls at your chosen frequency,
regression detection, AI-drafted fixes (if not in Audit mode),
auto-execution of whatever you've opted into (if in Autopilot mode), and
notifications for anything that needs your attention.
