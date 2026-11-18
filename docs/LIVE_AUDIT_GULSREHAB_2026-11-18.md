# RankPilot AI: live audit of the Guls Rehab project (18 Nov 2026)

Scope: read-only browser session on https://rankpilot.bugsnap-ai.com, project **Guls Rehab** (https://gulsrehab.com/). Navigation, tab clicks and "Show synced data" (display only) were used. Nothing was submitted, approved, applied, crawled, synced or disconnected. Some pages' own read endpoints (history, growth journey) perform a lazy back-fill of snapshots on first view; that is a write side effect of a GET and is listed as ISSUE-14.
Credentials were typed into the chat by the user. They are not stored in this file or in any artefact; the session file was deleted. **Rotate that password.**

Labels: **[O]** directly observed, **[I]** inference, **[U]** unverified / not tested.

## A. Executive summary
- The application is stable and usable: every project tab loaded, no HTTP errors and no page errors on any page visited **[O]**. Layout holds at 390 px and 820 px with no horizontal overflow **[O]**.
- Guls Rehab has a real technical baseline: 143-146 pages, 18 stored snapshots, 106 completed automated tasks, Search Console and GA4 connected, a Sanity connector **[O]**.
- **Actual SEO improvement cannot yet be verified because historical evidence is insufficient.** Only 4 days of stored history (14-18 Nov), every snapshot is "rebuilt from stored scores", and Search Console data is 97 query rows with 0 clicks and 1-2 impressions each **[O]**.
- The History page currently reports the project as **declined** (health 96.66 to 90.85). That comparison is not like-for-like (see ISSUE-02), so it is misleading in both directions.
- Several screens contradict each other (work done, Search Console availability, weekly report impressions). These are the main risks for a customer-facing "proof of progress" product.

## B. UX audit (module by module)
| Module | Observation | Rating |
|---|---|---|
| Dashboard | Clear website list, onboarding checklist (10 of 13 steps) **[O]** | Good |
| Overview | Score ring, clickable tiles, wrapping tabs **[O]**. Settings block (automation, crawl frequency) is long and sits below the metrics | Good |
| Crawls | Complete list of 20+ crawls with times and 146/146 pages **[O]** | Good |
| Pages | URL, status, indexability, open-finding count **[O]**. No visible sort/filter checked **[U]** | OK |
| Findings | Rule code + URL + severity + status; CSV download **[O]**. Rule codes (HEADING_HIERARCHY_SKIP) are shown raw, with no explanation in the list | Fair |
| Opportunities | Impact/confidence/effort/score shown **[O]**. 112 open items with near-identical titles ("Shorten an overlong page title"), no grouping | Fair |
| Tasks | 115 rows each showing only "set_title / risk tier 1 / APPROVAL: NOT_REQUIRED / COMPLETED" **[O]**: no page URL, before/after text or time visible in the list | Poor |
| Integrations | Honest state; GSC and GA4 show synced-row counts **[O]** | Good |
| Reports | Weekly cards, includes "not attributed to any change" note **[O]** | Fair (see ISSUE-04) |
| Keywords | Rich tab set; "every number is labelled verified or estimated" **[O]**. Only the Overview tab text was read; other sub-tabs **[U]** | Not fully audited |
| Growth Plan | Journey, plan, recommendations render **[O]** | Good, with count confusion (ISSUE-08) |
| History & Progress | Complete but see ISSUE-01 to 03, 06 | Needs fixes |
Accessibility: keyboard Tab order is logical and a 2 px outline is present on every focused element tested (14 stops) **[O]**. Contrast was not measured **[U]**. 3-6 interactive elements per page are smaller than 32 px **[O]**.

## C. Functional test execution
| ID | Module | Test | Expected | Actual | Status | Severity |
|---|---|---|---|---|---|---|
| T01 | Auth | Login with supplied account | Lands on dashboard | Landed on /dashboard | Pass | n/a |
| T02 | Dashboard | Find Guls Rehab | Project listed | Listed, VERIFIED/ACTIVE | Pass | n/a |
| T03 | Project | Open all 9 tabs | Each renders | All rendered, no API 4xx/5xx | Pass | n/a |
| T04 | Project | Keywords, Growth Plan, History, Report routes | Render | Rendered | Pass | n/a |
| T05 | Integrations | Show synced data (GSC, GA4) | Rows shown | 97 and 40 rows | Pass | n/a |
| T06 | History | Baseline exists and is labelled | Yes | Yes, flagged "rebuilt" | Pass | n/a |
| T07 | History | Work-done counts match Tasks | Match | 0 vs 106 completed / 145 applied | Fail | High |
| T08 | History | Search Console availability matches Integrations | Match | "No data stored" vs 97 rows | Fail | High |
| T09 | Reports | Weekly impressions match synced rows | Match | 0 vs rows with impressions in the week | Fail | High |
| T10 | Responsive | 390 px and 820 px on 4 pages | No overflow | No overflow | Pass | n/a |
| T11 | Accessibility | Keyboard focus visible | Visible | Visible | Pass | n/a |
| T12 | Filters, sorting, pagination, date range selectors | Work | not exercised | Not Tested |  |  |
| T13 | Recommendation detail, approve/apply, AI proposal | Work | writes / paid AI | Not Tested: approval required |  |  |
| T14 | Crawl now, Sync now, connector changes | Work | mutate data | Not Tested: approval required |  |  |
| T15 | Keyword sub-tabs, competitor gaps (0 competitors tracked) | Work | partly read | Not Tested |  |  |

## D. SEO audit
- **Technical:** 0 critical, 2 warnings, 323 informational findings **[O]**. The sampled findings are HEADING_HIERARCHY_SKIP, EXTERNAL_LINK_REDIRECT, TITLE_TOO_LONG, IMAGE_MISSING_DIMENSIONS on real URLs of the site, which looks plausible. Each was not individually verified against the live page **[U]**.
- **Open title work:** many "Shorten an overlong page title" opportunities remain while 106 `set_title` tasks completed. The earlier decision to postpone the 74-title repair explains this **[I]**.
- **On-page quality:** the business profile suggestions list real services found on the site (laser hair removal, PRP, physiotherapy, Hydrafacial…) and dropped unsupported ones by design **[O]**. AI proposals were not triggered, so factual preservation of titles/meta was **[U]**.
- **Keywords:** 97 first-party GSC queries (tiny volumes), 126 AI keyword ideas clearly labelled "not verified search data", 0 competitors tracked **[O]**. No search volume or difficulty is presented as verified.
- **Competitors:** none added, so competitor gaps cannot be assessed **[O]**.
- **Local SEO:** "physiotherapist near me" appears at positions 1.0 and 201.0 on different days **[O]**, which suggests unstable or very thin data rather than a ranking **[I]**.

## E. SEO progress assessment
| Metric | Baseline (14 Nov, rebuilt) | Current (18 Nov) | Difference | Evidence / comment |
|---|---|---|---|---|
| Health score | 96.66 | 90.85 | -5.81 | Not like-for-like (ISSUE-02) |
| Technical score | 95 | 94.79 | -0.21 | RankPilot crawl |
| On-page score | 95.17 | 93.92 | -1.25 | RankPilot crawl |
| Content score | 99.79 | 99.79 | 0 | RankPilot crawl |
| Performance score | Not available | 74.90 | n/a | Added after baseline |
| Critical issues | 0 | 0 | 0 | |
| Warnings | 2 | 2 | 0 | |
| Info issues | 281 | 323 | +42 | |
| Pages crawled | 146 | 146 | 0 | |
| GSC clicks / impressions / CTR / position | Not available | Not available in History | n/a | 97 raw rows exist, 0 clicks |
| GA4 sessions | Not available | Not compared | n/a | 40 rows exist, not shown in History |
| Pages optimized / recommendations implemented | 0 | 0 (but 106 tasks completed) | n/a | Contradiction (ISSUE-01) |
**Conclusion:** no verifiable improvement or decline in search visibility. Technical health is high and stable (not a Google metric).

## F. History tracking assessment
- Baseline exists, dated 14 Nov 2026, flagged as rebuilt, partial, per-issue detail not kept **[O]**.
- 18 snapshots stored, all `reconstructed: true` **[O]**; no live-recorded snapshot exists yet **[I]** (the history feature was deployed after these crawls).
- Comparison works and labels "Not available" instead of zero **[O]**.
- Score series: 96.66 → 96.24 → **90.92 (15 Nov 06:02, a step of -5.3)** → 90.63 → 91 → 87.25 (18 Nov 01:02) → 90.85 **[O]**. The step on 15 Nov coincides with the Performance score first appearing **[I]**.
- Implementation history does not reach the History page (ISSUE-01). Historical progress cannot be established yet.

## G. Prioritised backlog
| ID | Title | Module | Sev. | Type | Evidence | Fix |
|---|---|---|---|---|---|---|
| ISSUE-01 | "Pages optimized 0 / Recommendations implemented 0" while 106 tasks completed and Growth Plan says 145 changes applied | History | High | Data integrity | History overview "work" block vs Tasks tab | Count work from executed tasks/change records with validation status, not only the recommendation-stage log |
| ISSUE-02 | Baseline vs current health score compared although the scoring composition changed (Performance absent at baseline) | History | High | Data integrity / SEO quality | Performance "Not available" → 74.90; -5.3 step on 15 Nov | Store score components; compare like-for-like or flag "composition changed" and suppress "Declined" |
| ISSUE-03 | History says "No Search Console data stored" while Integrations shows 97 synced rows and Growth Plan says GSC data available | History / Growth | High | Data integrity | Screens above | Aggregate stored query rows into property/daily totals or label the source and why totals are absent |
| ISSUE-04 | Weekly report 9-16 Nov shows 0 impressions although synced rows have impressions on 9, 10, 12, 13 Nov | Reports | High | Data integrity | Reports vs synced rows | Fix aggregation / date window; show Not available when not computable |
| ISSUE-05 | Tasks list shows no page, before/after or date | Tasks | Medium | UX | 115 identical rows | Show URL, field, old to new value, time, validation result |
| ISSUE-06 | Snapshot pickers list 18 identical "Nov 14, 2026 (rebuilt)" labels | History | Medium | UX | Dropdowns | Add time and score; collapse same-day |
| ISSUE-07 | Open issues "Not available" in comparison while 325 open | History | Medium | Data integrity | Compare table | Use stored finding counts when per-issue detail is missing |
| ISSUE-08 | Different recommendation counts (112 opportunities, 149 "to review", 302 total) without explanation | Growth / Overview | Medium | UX | Three screens | Explain or unify counts |
| ISSUE-09 | "New since baseline 358" vs info issues +42 | History | Medium | Data integrity | Overview vs compare | Define and document; baseline issue list is absent |
| ISSUE-10 | Pages crawled 146 (snapshots) vs 143 (overview/pages) | Overview | Low | Data integrity | Screens | Reconcile definition |
| ISSUE-11 | Raw rule codes and 112 near-duplicate opportunities | Findings/Opportunities | Low | UX | Lists | Plain-language names, group by rule |
| ISSUE-12 | 3-6 touch targets under 32 px per page | All | Low | Accessibility | Measured | Increase hit areas |
| ISSUE-13 | Onboarding shows 10/13 complete; remaining steps not audited | Dashboard | Low | UX | Dashboard | **[U]** |
| ISSUE-14 | GET pages (history, journey) write lazy back-filled snapshots | API | Low | Architecture | Code knowledge | Move back-fill to a job or explicit action |

## H. Scorecard (evidence-limited)
| Area | Score | Basis / limit |
|---|---|---|
| UX/UI | 7/10 | All pages read; interactions beyond navigation not exercised |
| Functional reliability | 8/10 | No errors anywhere visited; writes not tested |
| SEO intelligence quality | 6/10 | Plausible findings; AI output, keywords sub-tabs, competitors not tested |
| Recommendation quality | 5/10 | Lists reviewed; no detail view, approval or proposal tested |
| Historical progress tracking | 4/10 | Exists and is honest about gaps, but 3 contradictions and a misleading baseline |
| Data integrity | 4/10 | ISSUE-01 to 04, 07, 09, 10 |
| Responsive | 8/10 | 2 viewports, 4 pages |

## I. Next steps
- **P0:** ISSUE-01, 02, 03, 04. Until fixed, do not show the History page or reports to customers as proof of progress.
- **P1:** ISSUE-05, 06, 07, 09; collect live (non-rebuilt) snapshots over the coming weeks; add competitors.
- **P2:** ISSUE-08, 10, 11, 12.
- **P3:** move back-fill out of GET (ISSUE-14); contrast audit.

## J. Final verdict
1. Usable for a new customer? **Yes for crawling, findings and fixing; no for "prove progress".**
2. Meaningful baseline? **Technical yes; search-performance baseline no** (reconstructed, 4 days).
3. Recommendations relevant and actionable? **Plausible and specific by URL; individual proposals untested.**
4. Is progress genuinely tracked? **Partly: scores and issues yes, implementation history and Google data no.**
5. Improvement demonstrable with evidence? **No, not yet.**
6. Incomplete or broken: History work counts, Search Console totals, weekly report impressions, like-for-like score, task detail.
7. Fix next: ISSUE-01 to 04.

---

## K. Fix status (same day)

All fixes are covered by automated tests (backend 1329 passed, UI 75 passed). **They are not yet verified on the live site**; re-run the audit after deploying.

| Issue | Status | What changed |
|---|---|---|
| ISSUE-01 | Fixed | Root cause: execution wrote change records with no page, so every count that used the page read 0. New records now carry the page; a migration fills the page for existing records; counts and per-page history resolve through the task's opportunity. History now also shows "Changes applied". |
| ISSUE-02 | Fixed | When the overall score averages different components (performance added later) it is shown as "Not comparable", with a like-for-like figure over the shared components. |
| ISSUE-03 | Fixed (wording + consistency) | History and Growth Plan now agree: stored query rows are reported, with the reason that daily totals are collected on the next scheduled sync or Sync now. **Daily totals themselves still appear only after that sync runs.** |
| ISSUE-04 | Fixed for new reports | A week with no stored rows is "Not available", never 0. **The already-stored report for 9-16 Nov keeps its old zeros**; it is a stored record and was not rewritten. The next weekly report is correct. |
| ISSUE-05 | Fixed | Task rows show a readable action, target page and new value. |
| ISSUE-06 | Fixed | Snapshot pickers show date, time and score. |
| ISSUE-07 | Fixed | Open issues derived from stored per-severity counts when the total was not kept. |
| ISSUE-08 | Fixed | Stage filter, "N shown of M in total", clearer wording, note on the Overview tile. |
| ISSUE-09 | Explained | The 358 is correct by definition (includes issues already fixed); the History page now says so. Not a calculation bug. |
| ISSUE-10 | Fixed | Overview tile renamed "Pages found" with a note when the last crawl fetched more URLs (146 fetched vs 143 stored). |
| ISSUE-11 | Fixed | Plain-language rule names beside the code. |
| ISSUE-12 | Fixed (CSS) | Minimum 32 px height for enabled buttons and back links. Not re-measured. |
| ISSUE-13 | Not done | Onboarding steps were not audited. |
| ISSUE-14 | Mitigated | The scheduler now performs the history back-fill off the request path; the history pages still do it once, lazily, for projects it has not reached yet. |

Deploy: `git pull`, `alembic upgrade head` (new head `565348bb39ef`), rebuild web, restart api, worker, scheduler and web.
