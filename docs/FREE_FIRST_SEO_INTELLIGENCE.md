# Free-First SEO Intelligence — feasibility, methodology, status

RankPilot uses no paid SEO data API (no Ahrefs, Moz, Semrush, Majestic, DataForSEO or paid keyword/rank providers). Every number is
either measured from the customer's own site, taken from the customer's own Google data, or a transparent RankPilot calculation.

Data labels used everywhere: **Verified** (observed from a source page or Google), **RankPilot calculated**, **AI-generated**,
**Estimated**, **Not available**, **Not tested**, **Stale**. Missing data is never shown as zero and never counted as zero in a score.

## Feasibility matrix

| Capability | Feasible free? | How it is done | Status |
|---|---|---|---|
| Domain Rating / Authority Score / Trust Flow | **No** (needs a web-scale link graph) | Never imitated. Replaced by *Domain Quality*, a differently named, documented score | Built (A) |
| Domain Quality Assessment | Yes | Calculated from the crawl, snapshots and Search Console totals | Built (A) |
| Backlink discovery | **No** (no free web-wide index) | Not claimed. Customer supplies linking pages (typed, pasted, Search Console links export) | Built (B) |
| Backlink verification (live, anchor, rel, destination, location) | Yes | Fetch the source page under robots.txt and SSRF rules, parse anchors pointing to the site | Built (B) |
| New / lost / changed link history | Yes | `backlink_checks` rows with a diff per check; an outage does not mark a live link lost | Built (B) |
| Referring domains, anchor mix, follow ratio | Yes, for verified links only | Labelled "not a count of every link" | Built (B) |
| Keyword search volume, difficulty, CPC | **No** | Never stored or invented. Google Search Console impressions and positions are shown as the real demand evidence | Existing |
| Keyword ideas, intent, clustering | Yes | Existing keyword ideas (seed/GSC/AI/competitor gap), labelled by classification | Existing, extended in C |
| Local Lighthouse | Feasible, heavy | Chromium is installed in the app image; run is rate-limited and lab-labelled. PageSpeed Insights (free API) already provides field + lab data | PSI existing; local run planned (D) |
| Content quality, topical coverage, E-E-A-T signals | Partly | Deterministic checks on crawled text; AI wording labelled AI-generated | Planned (E) |
| Technical audit extensions | Yes | Added to the existing rule engine, not a new crawler | Planned (F) |
| Competitor intelligence | Public pages only | Existing competitor crawler; no competitor traffic or ranking numbers | Existing, extend in G |
| History and trends | Yes | Reuses ProjectSnapshot/metric history; assessments are append-only per crawl | Built for A/B |

## Domain Quality (formula `authority-v1`)

* **Purpose:** show whether the site's own structure, content, crawlability and visibility are in good shape. It says nothing about
  links from other websites.
* **Inputs:** latest page snapshots, internal link graph, findings, Search Console property totals, snapshot history. Stored whole in
  `authority_assessments.inputs_json`, so every score can be recomputed (`score_from_inputs`) and is tested to match.
* **Signals and weights:** Internal Link Strength 20%, Content Coverage 15%, Crawl Health 15%, Indexability Health 15%,
  Topical Consistency 10%, Organic Visibility 10%, Website Structure Quality 10%, Content Freshness 5%.
* **Normalization:** each signal is 0–100 from the ratios shown on the page ("How it is calculated").
* **Missing data:** a signal without enough data is `not_available` and dropped; the remaining weights are re-normalised.
  `coverage` = share of total weight that had data; `confidence` = high ≥ 85%, medium ≥ 60%, otherwise low; none when nothing is available.
* **Limitations:** blind to external links, brand strength and ranking positions; topical consistency is a term-overlap heuristic;
  freshness needs 30+ days of crawl history.
* **Update frequency:** one row per completed crawl, or on demand (rate limited). Rows are never edited; a formula change bumps
  `formula_version` and comparisons across versions are flagged.

## Backlinks

* No total backlink count is ever shown. Statuses: unchecked, live, link_removed, unreachable, blocked_by_robots, error.
* Limits per call: 25 checks, 0.5 s delay, 40 s budget; up to 500 URLs per import; own-site, private and unsafe URLs rejected.
* robots.txt of the linking site is respected; no login, CAPTCHA or paywall bypass.

## Endpoints

`GET /authority`, `POST /authority/refresh`, `GET /backlinks`, `POST /backlinks/import`, `POST /backlinks/check`,
`GET /backlinks/{id}/history`, `DELETE /backlinks/{id}` under `/organizations/{org}/websites/{site}`. Viewer reads, editor writes.

## Remaining modules

C (opportunity scores), D (local Lighthouse), E (content intelligence), F (technical), G (competitors) and I (scoring catalogue for
all scores) are tracked in the project task list and will be appended here as they land.
