# Free-First SEO Intelligence — delivery report

**A. Summary.** RankPilot now offers authority, backlink, keyword, content, technical, speed, competitor and history intelligence with no
paid SEO data source. Where free data cannot exist (DR/DA, web-wide backlinks, search volume, difficulty, competitor traffic) the product
says so and offers the nearest honest, useful alternative.

**B. Feasibility matrix.** See `docs/FREE_FIRST_SEO_INTELLIGENCE.md`.

**C. Built (module → code → UI).**
| Module | Backend | UI |
|---|---|---|
| A Domain Quality + history | `app/authority/assessment.py`, `models/authority.py`, computed after every crawl | Authority & Backlinks tab |
| B Backlinks (add/import, verify, history, referring domains) | `app/authority/backlinks.py` | Authority & Backlinks tab |
| C Ranking Opportunity, clusters, keyword→page map, cannibalization leads | `app/keywords/opportunity_score.py`, `app/intelligence/keywords.py` | Authority tab, SEO Intelligence → Keyword map |
| D Local lab speed (+ Lighthouse when installed) | `app/intelligence/lab.py` | SEO Intelligence → Speed (lab) |
| E Content intelligence (depth, structure, topical coverage, trust evidence, snippet candidates, near-duplicate titles) | `app/intelligence/content.py`, run after every crawl | SEO Intelligence → Content |
| F Technical (hreflang, lang, OG/Twitter, favicon, security headers, http/www canonicalisation, robots/sitemap, redirect chains, schema required properties) | `app/intelligence/technical.py` | SEO Intelligence → Technical |
| G Competitor structure | `app/intelligence/competitors.py` | SEO Intelligence → Competitors |
| H History | Append-only `authority_assessments`, `backlink_checks`, `intelligence_runs`; History endpoints per analysis | Score + last-updated on each page |
| I Scoring framework | `docs/RANKPILOT_SCORING_METHODOLOGY.md` | Formula version and "how" shown in the UI |

**D. Free sources used.** Own crawl and snapshots; Google Search Console (existing connection); PageSpeed Insights free API (existing);
public pages fetched under robots.txt (backlink verification, competitor pages); the server's own headless Chromium.
No new third-party service or account was added.

**E. Not possible for free, and what replaces it.** DR/DA/AS/TF/CF → Domain Quality (clearly different). Backlink discovery → customer-supplied
sources plus verification. Search volume/KD/CPC → Search Console impressions and positions. Competitor traffic/rankings/backlinks → public
page structure only. Full Lighthouse → runs when the CLI is installed, otherwise Not tested, with PageSpeed Insights as the free alternative.

**F. Safety.** Public URLs only (SSRF checks on every redirect), robots.txt respected for third-party pages, no login/CAPTCHA bypass, per-endpoint
rate limits, bounded batches (25 backlink checks, 40 s), tenant isolation via organization membership (tested), no writes to customer sites.

**G. Tests.** `tests/test_authority.py` (12) and `tests/test_intelligence.py` (12) cover: unavailable-not-zero, reproducibility from stored
inputs, formula-change flag, idempotence per crawl, link extraction (anchor/rel/location), SSRF/own-site rejection, lost/changed/outage history,
referring-domain counts, the opportunity score, clustering and cannibalization, technical checks with unknowns, schema validation, a real
headless-browser measurement, competitor structure, and API flows with cross-tenant denial. Playwright: `authority.spec.ts`, `intelligence.spec.ts`.

**H. Deploy.** `git pull`, `alembic upgrade head` (adds `backlinks`, `authority_assessments`, `backlink_checks`, `intelligence_runs`),
rebuild web, restart api, worker, web. Optional: `npm i -g lighthouse` on the VPS and set `LIGHTHOUSE_BIN` to enable full Lighthouse runs.

**I. Known limits.** Domain Quality ignores external links; freshness needs 30 days of crawls; content analysis has no body text so answer
quality and near-duplicate prose are Not tested; technical checks sample the homepage; the local lab number varies per run; cannibalization
is a lead, not proof. Competitor analysis requires competitors to be added and crawled first.

**J. Follow-ups.** Backlinks are re-verified automatically every Wednesday (25 per project per run; "Verify links" does it on demand). Pulling the new scores into the
client progress report; on-demand technical sampling of more than the homepage.

**K. What the user should do.** Deploy (H), open Authority & Backlinks and SEO Intelligence on a real project, add known linking pages,
and run each analysis once to create the first baseline.
