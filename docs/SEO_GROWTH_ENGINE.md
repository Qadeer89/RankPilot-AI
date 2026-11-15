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
