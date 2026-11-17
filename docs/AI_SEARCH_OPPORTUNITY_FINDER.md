# AI Search Opportunity Finder — audit, plan and methodology

Native enhancement of the SEO Growth Engine. Nothing here is a second application: it reuses the Search
Console integration, the keyword store, the growth-recommendation lifecycle, the AI runner and the crawler.

## 1. Repository audit (what exists, what is reused)

| Need | Existing code | Decision |
|---|---|---|
| Search Console auth, token refresh | `integrations/google_search_console.py`, `token_store` | **Reused unchanged** |
| GSC data store | `KeywordObservation` (website, query, page_id, date, country, device, clicks, impressions, ctr, position) filled by `search_console_sync.sync_search_performance` | **Reused as the only metrics store.** Discovery is computed from it; no metrics are copied into new tables except a baseline snapshot taken when a person acts on a query |
| Country normalisation | `core/countries.normalize_country` (GSC alpha‑3 → alpha‑2, `ZZ` unknown) | **Reused**; filters call it |
| Page index | `Page`, `PageSnapshot` (title, meta, headings, word count, schema) | **Reused**; full body text is not stored, so it is fetched live (SSRF-safe `safe_fetch`) when a query is analysed |
| Cannibalisation / near-page-one signals | `opportunities/search_trend_signals.py` | Same definitions reused for consistency |
| AI provider, budget, cost ledger, entitlement | `ai/runner.run_ai_agent`, `AgentRun` | **Reused**; one new agent type `ai_search_answer` |
| Recommendation lifecycle | `GrowthRecommendation` (open/approved/rejected/done) + `growth/lifecycle.describe` | **Reused**: each AI-search recommendation is a `GrowthRecommendation` of type `ai_search_answer`; richer statuses are derived, not stored twice |
| CMS execution | `execution/service` operations: `set_title`, `set_meta_description`, `set_canonical`, `set_alt_text`, `set_schema_json` | **Finding: there is no operation that edits page body content.** See §6 |
| Post-change crawl | `growth/recrawl.schedule_post_change_crawl` | Reused for verification |
| Before/after monitoring | `growth/performance.py` (page level) | Same windows/caveats; query-level variant added |

### Gaps found in the audit
1. **GSC sync fetched at most 1,000 rows with no pagination**, so a site with more query×page×date×country×device rows silently lost most long-tail queries. Fixed in phase 1 (paged fetch with `startRow`, truncation reported).
2. Sync window defaults to 28 days; 3/6-month views need a backfill. Data coverage (first/last stored day) is shown so a short window is never presented as a longer one.
3. GSC never returns anonymised queries and returns only part of rare long-tail queries. This is a property of Google's data and is stated in the UI.
4. No page body text is stored (only headings, counts, hashes) → fetched live for analysis.
5. Search type is "web" only (what the sync requests); image/video/news are not covered.

## 2. Plan / phases
P1 paged GSC sync, deterministic query classification, explainable scoring, page mapping, cannibalisation. P2 live page answer analysis, GEO‑readiness checklist, AI direct‑answer agent with deterministic quality checks. P3 findings table, APIs, lifecycle, verification, query‑level monitoring. P4 dashboard. P5 real‑data validation script, delivery report.

## 3. Query classification (deterministic, explainable)
A query can carry several labels; the original text is never altered.
* **question** — starts with an interrogative or auxiliary (what, how, why, which, where, when, who, is, are, can, could, should, does, do, will, plus Roman‑Urdu starters kya/kaise/kyun/kab/kahan/kitna) with at least 3 words, or ends with `?`.
* **long_tail** — at least `long_tail_min_words` (default 5) words.
* **conversational** — at least 6 words AND (a question, or first/second‑person phrasing such as "I", "my", "should I", "for me", "do you").
* **comparison** — `vs`, `versus`, `difference between`, `compare`, `better than`, `best … for`, `… or …` with comparative cue.
* **problem_solution** — problem/outcome cues: "not working", "fix", "how to stop", "can't", "error", "struggling", "get rid of", "help with".
* **very_long** — matches the configurable regex, default `^(?:\S+\s+){7,}\S+$` (8+ words). It is RE2‑compatible (no look‑around, no back‑references); a validator rejects patterns that Search Console's RE2 engine would not accept. A long query is **not** automatically a question.
AI classification is used in the per‑query analysis (the agent returns the search intent and whether the page's purpose matches); it is not run over thousands of queries because that would cost money without evidence of value.

## 4. Opportunity scoring (0–100, every point explained)
Factors shown beside each score: demand (impressions, log scale, up to 30), position headroom (4–20 best, up to 25; 1–3 small; 21–50 partial; >50 none), CTR vs **this site's own** median CTR at a similar position (up to 15, only when at least 5 comparable queries exist; no external benchmark is invented), page relevance (crawled landing page exists, up to 10), answer coverage from the page's title/headings (up to 15), trend (second half of the window vs first, up to 5), intent fit (question/conversational, up to 5).
Tiers: **low_priority** (impressions below the minimum or no evidence) → **content_gap** (page missing or its title/headings barely cover the query) → **high_opportunity** (CTR clearly below the site's own benchmark, position ≤ 20, page exists) → **ranking_improvement** (position 4–30 with a relevant page) → otherwise low priority. Low CTR alone never creates an opportunity. No search volume, difficulty or CPC appears anywhere.
If two pages each hold a material share of a query's impressions, the query is flagged `needs_review` (cannibalisation) and no single page is silently chosen.

## 5. GEO / AI‑search content readiness
A transparent checklist (pass / warn / fail with the evidence for each): direct answer under a matching heading, concise answer paragraph, descriptive headings, lists/tables, examples or figures, outbound sources where claims are made, internal links, adequate depth, title/meta aligned with the query, structured data present. The label (Strong / Moderate / Needs work) is the share of checks passed. **It is a content‑quality assessment, not a visibility score.** Search Console queries are Google Search data, not ChatGPT/Gemini prompts. AI‑platform visibility is shown as **unmeasured** because RankPilot has no verified data source for it.

## 6. Execution limits (honest)
The CMS pipeline can change title, meta description, canonical, alt text and JSON‑LD. It **cannot** insert a direct‑answer section or FAQ into body content. Therefore: approved AI‑search recommendations are delivered as a copy‑ready draft; the person adds it in their CMS, marks it implemented, and RankPilot then (1) runs a targeted crawl, (2) live‑checks that the suggested heading/answer is on the public page, (3) records the baseline and starts query‑level monitoring. Nothing is published automatically. A body‑edit operation for WordPress is possible later but writes post content and needs its own approval.

## 7. Monitoring
Query+page stats for equal windows before and after the implementation day (7/28/90 days), the after window flagged incomplete until Search Console has reported all of it. The numbers are a correlation, never proof of cause.

---

## 8. Delivery report

### What was built
| Area | Where |
|---|---|
| Paged Search Console fetch (25,000 rows/page, truncation reported) | `integrations/google_search_console.py`, `search_console_sync.py` |
| Query classifier + RE2 validator | `ai_search/classify.py` |
| Discovery, scoring, tiers, cannibalisation, data-coverage warnings | `ai_search/discovery.py` |
| Live page reading, answer analysis, readiness checklist | `ai_search/page_content.py`, `answer_analysis.py`, `geo.py` |
| AI direct-answer agent + deterministic quality pass | `ai_search/agent.py` (new agent type `ai_search_answer`) |
| Findings, approval, verification, monitoring | `models/ai_search_finding.py`, `ai_search/service.py`, `monitoring.py` |
| API (`/organizations/{org}/websites/{site}/ai-search/...`) | `api/v1/endpoints/ai_search.py` |
| UI: Keyword Intelligence → **AI Search Opportunities** | `components/ai-search/AiSearchFinder.tsx` |
| Live validation on real data | `scripts/validate_ai_search.py` |

Database: one new table `ai_search_findings` (migration `887338fe6a21`) and one new enum value; Search Console metrics are **not** duplicated (they stay in `KeywordObservation`). Recommendations reuse `GrowthRecommendation`.

### Test results (this environment)
Backend 1162 passed (about 110 new: classification, scoring with hand-computed values, discovery, page analysis, quality checks, API lifecycle, tenant isolation, roles, prompt-injection handling). Frontend: type-check and lint clean, 55 browser tests passed (10 new).

### Classification of each requirement
| Requirement | Status |
|---|---|
| Question / long-tail / conversational / comparison / problem queries, configurable regex, RE2 validation | Implemented and tested |
| AI-based classification of queries | **Partial**: the per-query AI analysis returns the search intent and whether the page fits it; it is not run over every query (cost, no evidence of value) |
| Paged GSC retrieval, date presets and custom range, country/device/page filters | Implemented and tested with fake Search Console responses |
| Search type other than web, anonymised queries | **Not available** (Search Console limitation / not synced) |
| Explainable scoring, tiers, own-site CTR benchmark | Implemented and tested |
| Page mapping, cannibalisation → review, no invented page | Implemented and tested |
| Live page analysis, direct answer, heading, FAQ only when useful, internal links restricted to the page's real links | Implemented and tested; **AI call verified once against the real model on a synthetic page** (found and fixed a schema-length bug) |
| Quality checks (figures, superlatives, invented links/contacts, stuffing, duplication, readability, intent) | Implemented and tested |
| GEO / AI-search readiness | Implemented as a transparent checklist; AI-platform visibility shown as **unmeasured** |
| Dashboard, filters, detail view, generate button | Implemented and UI-tested (fake API) |
| Statuses New … Completed | Implemented (derived) |
| Approval required, nothing published | Implemented and tested (no ChangeRecord/SEOTask is ever created) |
| **Apply through the CMS** | **Not implemented, by design**: no CMS operation edits body content. The person adds the approved text and marks it implemented; RankPilot re-reads the public page to verify |
| Targeted crawl after the change | **Not run**: the existing post-change crawl is tied to CMS change records. A live fetch of the page is used instead |
| Monitoring before/after, confounders, caveats | Implemented and tested with hand-computed numbers |
| **Validation on real GulsRehab Search Console data** | **Not done: blocked here.** This sandbox has no access to the project's Search Console data. Run `scripts/validate_ai_search.py` on the VPS (below); it reports "BLOCKED: insufficient real data" rather than inventing anything |
| CMS execution evidence | None (see above) |

### Run the real validation (VPS)
```bash
cd /opt/RankPilot-AI/apps/api && source .venv/bin/activate
python scripts/validate_ai_search.py --site gulsrehab --window 3m
python scripts/validate_ai_search.py --site gulsrehab --window 3m --analyze-top 1 --save
```
For 3-/6-month windows the stored history must reach that far; the screen and script say how far the stored data goes.

### Known limitations
1. Search Console omits anonymised and very rare queries, so some long-tail searches never appear.
2. Only web-search data is synced; the stored window starts when syncing started.
3. CTR is judged against this site's own median at similar positions; with fewer than 5 comparable queries the factor is not scored.
4. Query/page coverage in the list uses the page's title and headings only; the full-text analysis happens when a person asks for a recommendation.
5. Body-content changes are manual. A WordPress "insert section" operation is possible but writes post content and should be a separate, approved piece of work.
6. Queries in languages other than English are classified only by length (Roman-Urdu question starters are recognised).
7. The AI draft is a recommendation. Facts it could not find on the page are listed as "needs your input", not invented.

### Deployment and rollback
```bash
cd /opt/RankPilot-AI && git pull origin claude/serene-goodall-32a2wo
cd apps/api && source .venv/bin/activate && alembic upgrade head   # -> 887338fe6a21
cd ../web && npm run build
pm2 restart rankpilot-api rankpilot-worker rankpilot-scheduler rankpilot-web
```
Rollback: restart the previous commit; the new table and enum value are ignored by old code. `alembic downgrade 31eaadaff61a` drops `ai_search_findings` (the enum value remains, which is harmless). Existing sync behaviour changed in one way: it now pages through all Search Console rows instead of the first 1,000, so the next sync can store more rows than before.
