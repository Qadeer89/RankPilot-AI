# Marketing feature inventory

What the public website (`apps/web/src/app/(site)`) is allowed to claim. Every item below was checked against the code. Copy lives in
`apps/web/src/lib/marketing.ts`; change this document and that file together.

## Advertised (implemented and reachable in the application)

| Claim | Evidence in the product |
|---|---|
| Website SEO audit with evidence, grouped findings and fix guidance | crawler + rule engine, Findings tab (`FindingsGroups`) |
| Technical SEO intelligence (redirects, robots/sitemap, social tags, structured data, mobile, indexability) | `app/seo_rules`, `app/intelligence/technical.py` |
| AI recommendations, approved by the user, 30-day plan | Growth Plan, `app/growth`, approval gates |
| Keyword intelligence, clusters, keyword-to-page mapping, ranking opportunities, country analysis | Keywords page, `app/keywords`, `app/intelligence/keywords.py` |
| Competitor analysis from public pages | `app/competitors`, `app/intelligence/competitors.py` |
| Content optimization via approved changes (titles, descriptions, canonical, schema, alt text) | `app/execution`, connectors |
| Google Search Console integration (read-only) incl. indexing status | `app/integrations/google_search_console.py`, `url_inspection_sync.py` |
| Google Analytics 4 integration (read-only) | `app/integrations/google_analytics.py` |
| History, saved baseline, progress report | `app/history` |
| Recommendation lifecycle and live verification | recrawl/verify-live, Tasks/Recommendations |
| Connectors: WordPress, Webflow, Sanity, GitHub, Slack notifications | `app/execution`, `app/notifications` |
| Per-project subscription, monthly/yearly, trial, cancel from Billing | `app/billing`, `/dashboard/billing`; prices read live from `GET /public/pricing` |

## Advertised with a label

* **Shopify: Beta.** Implemented and tested against a simulated store; not yet verified on a real store.

## Deliberately not advertised

* Local SEO (postponed), Paddle billing (postponed), full Lighthouse (needs the CLI installed on the server; the local lab measurement is not mentioned).
* Backlink discovery, Domain Rating/Authority-style scores, search volume, keyword difficulty, competitor traffic: not possible without paid data.
* Any customer logos, testimonials, ratings, case studies, rankings, traffic figures or ROI claims: none exist.
* Integration logos: not used (trademarked artwork); text names with a monogram are shown instead.
* Analytics/cookie-consent tracking of CTA clicks: no analytics infrastructure exists, so none was added.

## Billing facts the pages state (from `app/billing` and the Billing page)

* Price per project (website), monthly or yearly; amounts and trial length come from the billing configuration at request time.
* One free trial per customer; further projects are billed from day one.
* A payment method is collected at checkout; first charge when the trial ends; cancel from the Billing page before then and nothing is charged.
* After a paid period starts, access continues to the end of that period.
* Every target country of a project is included.
* Creating an account does not require a payment method.
