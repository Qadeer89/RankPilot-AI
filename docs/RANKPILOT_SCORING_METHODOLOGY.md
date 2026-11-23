# RankPilot scoring methodology (free-first scores)

None of these scores is Domain Rating, Domain Authority, Authority Score, Trust Flow, Citation Flow or a Google score. They are
RankPilot's own calculations from data RankPilot holds. Common rules for all of them:

* **Missing data is never zero.** A part without data is "Not available", left out, and the remaining weights are re-normalised.
* **Coverage** = share of total weight that had data. **Confidence** = high (coverage ≥ 85%), medium (≥ 60%), low, or none.
* **Reproducible.** Inputs are stored with each result; formula versions are stored and changes are flagged when comparing runs.
* **Append-only history.** Results are never edited; baselines are never overwritten.

| Score | Version | Purpose | Inputs | Parts and weights | Limitations | Update |
|---|---|---|---|---|---|---|
| Domain Quality | `authority-v1` | Is the site's own structure, content and visibility healthy? | Crawl snapshots, internal link graph, findings, Search Console totals | Internal links 20, content coverage 15, crawl health 15, indexability 15, topical consistency 10, organic visibility 10, structure 10, freshness 5 | Blind to external links and ranking positions; topical consistency is a term-overlap heuristic; freshness needs 30+ days of history | Every crawl, or on demand |
| Content Quality | `content-quality-v1` | Depth, structure, topical coverage and trust evidence of the pages | Titles, headings, word counts, URLs, JSON-LD types, confirmed business profile | Depth 30, heading structure 25, topical coverage 25 (needs confirmed offerings), trust signals 20 | No body text stored, so answer quality and near-duplicate prose are Not tested; E-E-A-T is evidence only | Every crawl, or on demand |
| Technical Health | `technical-health-v1` | Live technical hygiene beyond the crawler rules | Homepage fetch, http/www variants, robots.txt, sitemap.xml, headers, stored schema | Pass 100 / warn 50 / fail 0 per tested check, equal weights | Samples the homepage and site root, not every page; security headers are not ranking factors | On demand (max 10/hour) |
| Ranking Opportunity | `ranking-opportunity-v1` | Which existing queries to work on first | Search Console rows, last 28 days | Demand 50 (log impressions), headroom 35 (position band), CTR gap 15 (site's own CTR in the same band; needs 5 peers) | No volume, difficulty or seasonality; ≥10 impressions required | On demand |
| Keyword clusters | `keyword-cluster-v1` | Group queries into topics, map them to pages, surface split pages | Search Console rows, last 28 days | Term-overlap clustering (Jaccard ≥ 0.5); cannibalization lead when ≥2 pages each hold ≥20% of a cluster's impressions | A lead to review, not proof of lost rankings | On demand |
| Local lab speed | `local-lab-v1` | One measured mobile page load | RankPilot's headless browser | No score; TTFB, DOM loaded, load, LCP, requests | Lab only, varies per run, not field data; Lighthouse runs only if installed | On demand (max 3/hour) |
| Competitor structure | `competitor-structure-v1` | Compare page depth/schema/headings and topic terms with crawled competitor pages | Public competitor pages already crawled | No score | No competitor traffic, rankings or backlinks, ever | On demand |
| Backlink analysis | (counts) | Verified links from pages the customer supplied | Source pages fetched under robots.txt | Counts, referring domains, follow ratio, anchor mix | Not a count of all links; no discovery | On demand (25 per call) |

Where a value comes from is shown in the UI beside it: Verified, RankPilot calculated, AI-generated, Estimated, Not available,
Not tested, Stale.
