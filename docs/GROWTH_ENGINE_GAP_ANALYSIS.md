# From SEO audit tool to organic growth engine: audit, gaps and roadmap

Date: 2026-11-18. Source: the "Master Product Implementation Prompt". This document maps what RankPilot already does
against that specification so that nothing working is rebuilt. Status words: **Have** (implemented and tested),
**Partial**, **Missing**. "Tested" means automated tests in this repository; none of the Shopify write paths has
been run against a real Shopify store.

## 1. What already exists (reuse, do not rebuild)

| Spec area | Existing implementation | Status |
|---|---|---|
| Crawl, technical + on-page findings (metadata, duplicates, broken links, alt text, headings, canonicals, sitemap, structured data, mobile, performance, indexability), respecting robots.txt, crawl limits, SSRF safety | `crawler/*`, `seo_rules/*` (38 rules), health score + history | Have |
| Works with no GSC/GA4 | Crawl, findings, AI keyword ideas, competitor analysis do not need Google | Have |
| Honest data labels | `KeywordDataClassification`: verified_first_party, verified_external_source, public_search_suggestion, ai_generated_idea, ai_estimated_relevance; UI badges; no volume/difficulty/CPC fields anywhere | Have |
| AI keyword ideas, intent, clusters, country-specific | `ai/keyword_discovery.py`, `keywords/*`, country normaliser | Have |
| Competitor content gaps from public pages | `competitors/*` (observed facts vs AI interpretation) | Have |
| GSC + GA4 sync, freshness, re-auth handling | `integrations/*` (paged GSC fetch), reauth flow | Have |
| Recommendation engine from real evidence | `growth/service.py` (`GrowthRecommendation`), `opportunities/*` | Have (two parallel systems, see gaps) |
| Approval -> apply -> validate -> rollback with audit | `execution/*`, `growth/lifecycle.py`, ChangeRecord before/after, post-change recrawl | Have |
| Before/after performance per change | `growth/performance.py` (page level), `ai_search/monitoring.py` (query level) | Have |
| CMS connectors | WordPress, Shopify, Webflow, GitHub, Sanity | Have (Shopify narrow, below) |
| Conversational query finder, claim/source checks | `ai_search/*` | Have |
| Billing, admin, multi-tenant isolation, domain-independent config | commercial system | Have |

## 2. Gaps against the specification

| # | Spec requirement | Finding | Status |
|---|---|---|---|
| G1 | Zero-data **business understanding** (type, niche, products/services, audience, objective, competitors; AI-suggested, user-corrected) | Only `business_description`, target countries/languages and an onboarding checklist exist. No structured business profile and no AI suggestion/review step | Partial |
| G2 | **Initial SEO baseline** state and message for a new project; dashboard that adapts to connected/unconnected data | Overview shows health and findings, and hints "connect Search Console" in places, but there is no explicit "baseline ready" state, no journey-based layout, no consistent data-source + date-range labelling on every panel | Partial |
| G3 | **Shopify catalog analysis**: list products, collections, variants, images, alt text, availability, existing SEO title/description | The connector can only locate a page/product by URL handle and read/write the SEO title and meta description metafields. It cannot list products or collections or read descriptions, images or variants | **Missing** |
| G4 | **Product SEO analysis** (missing/duplicate/weak titles, thin content, missing alt text, headings, product schema, overlapping targeting) | The crawler analyses rendered Shopify pages like any site; there is no product-level model, no product schema validation, no overlap detection | **Missing** |
| G5 | **Product keyword intelligence** (category/attributes/customer/intent per product) | Keyword discovery works from site-level seeds. Nothing is product-aware | **Missing** |
| G6 | **AI product optimizer** (SEO title, meta, product title, description, headings, alt text, schema notes, related links, FAQ) with fact preservation | None. Only title/meta drafting for generic pages exists | **Missing** |
| G7 | **Bulk product optimization** with filter, generate, review, approve individually, apply, track | None | **Missing** |
| G8 | **Collection SEO** | None | **Missing** |
| G9 | **Shopify validation** (re-read updated fields, record timestamp and before/after, mark implemented only after verification) | The generic pipeline does read-back for the two metafields and stores before/after. Not extended to product description, title or image alt text | Partial |
| G10 | **Content growth engine**: topic, intent, audience, page type, primary + supporting keywords, related existing pages, outline, internal links | `new_content` recommendations carry topic, keyword and rationale; there is no outline, page type, audience, related-pages or internal-link plan | Partial |
| G11 | **Unified recommendation record** with title, page, problem, evidence, why, solution, implementation steps, priority (Critical/High/Medium/Low), effort, benefit category, validation criteria, type (technical/on-page/content/keyword/product/internal link/competitor gap) | Two systems with different fields: SEO opportunities (impact/effort scores) and growth recommendations (priority low/medium/high, difficulty). No "Critical" level, no implementation-instructions field, no single list | Partial |
| G12 | **One lifecycle** IDENTIFIED -> RECOMMENDED -> APPROVED -> IMPLEMENTED -> VALIDATED -> MONITORING with edit, dismiss, reopen | Derived lifecycle exists for growth recommendations and AI-search findings; opportunities have their own states; no single vocabulary, no edit/reopen everywhere | Partial |
| G13 | **First 30-day action plan** generated from actual findings | Nothing | **Missing** |
| G14 | **Per-recommendation measurement** (original state, updated state, target keyword, GSC before/after, GA4, validation, no unsupported attribution) | Page-level timeline for CMS changes and query-level monitoring for AI-search changes. Not available for every recommendation type; GA4 not joined per recommendation | Partial |
| G15 | **Customer messaging** (no guarantees, realistic expectations) | Disclaimers exist in several screens (AI search, performance). No product-wide copy review | Partial |
| G16 | Scenario tests A-F as one acceptance suite | Individual features are tested; no scenario-level suite. Scenario B (Shopify) cannot be run for real without a store | Partial / blocked |

## 3. Constraints that change the plan
* **No real Shopify store has been connected in any test.** Everything Shopify-related can be built and tested against a faithful fake of the Admin API, but it must be reported as "implemented, unverified against a real store" until a development store and Admin API token are available.
* Shopify Admin API versioning and the exact fields (product `body_html`, `title`, image `alt`, SEO metafields `global.title_tag` and `global.description_tag`) must be confirmed against the current Shopify documentation before writing; this is checked at the start of the Shopify phase, not assumed.
* Search volume, difficulty and CPC stay unavailable. Product keywords remain AI-generated ideas unless a first-party Search Console query backs them.

## 4. Roadmap (controlled phases, each tested before the next)
1. **P1 Business profile + baseline state (G1, G2, G15).** Structured business profile with AI suggestions the user reviews; project baseline status; dashboard journey states ("Your initial SEO baseline is ready. Connect Google Search Console and Analytics to measure actual search performance"); data-source and date range labelled on every metric panel; no number shown without a source.
2. **P2 Unified recommendation record + 30-day plan (G11, G12, G13).** One read model over opportunities and growth recommendations with the specified fields and Critical/High/Medium/Low; one lifecycle vocabulary with edit, dismiss, reopen; a plan generated from the actual findings, scaled to site size.
3. **P3 Shopify read-only catalog + product SEO analysis (G3, G4).** Products, collections, images and alt text, variants, availability; issue detection; product schema checks.
4. **P4 Product keyword intelligence + AI product optimizer (G5, G6).** Fact-preserving drafts; fabrication checks (specifications, materials, certifications, discounts, warranty, availability) reusing the claim checker.
5. **P5 Bulk workflow, apply and verify (G7, G9).** Filter, generate, review, approve one by one, apply, read back, record before/after.
6. **P6 Collection SEO (G8).**
7. **P7 Content growth engine upgrade (G10).**
8. **P8 Per-recommendation measurement and scenario tests A-F (G14, G16),** with an honest report of what ran against real services.

## 5. Decisions needed from the owner
1. A **Shopify development store** (free through a Shopify Partner account) and a custom-app Admin API token with product and content read/write scopes, supplied through the secure credential form, to make Phase 3-5 testable for real. Without it, Shopify phases ship as "implemented, tested against a fake".
2. Whether Phase 1 and 2 should start now (they need no external access).
