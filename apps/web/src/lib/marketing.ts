// All public marketing copy lives here so every page says the same thing. Every capability below exists in the application today;
// anything planned or unverified is deliberately left out (see docs/MARKETING_FEATURE_INVENTORY.md).
import type { Metadata } from "next";

export const JOURNEY = ["Discover", "Analyze", "Plan", "Implement", "Validate", "Measure", "Improve"] as const;

export const PROBLEMS = [
  { t: "You do not know what is hurting your SEO", d: "Dozens of small problems hide across hundreds of pages, and no one tells you which ones matter." },
  { t: "Technical issues are hard to prioritise", d: "A long list of warnings is not a plan. You need to know what to fix first, and why." },
  { t: "Keyword opportunities stay undiscovered", d: "Your own Search Console data already shows where you almost rank, but it is buried in exports." },
  { t: "Competitor gaps are hard to see", d: "It is difficult to tell which topics competitors cover that your pages do not." },
  { t: "Advice is scattered across tools", d: "Audits in one place, keywords in another, notes in a spreadsheet. Nothing ties them together." },
  { t: "You cannot tell if changes worked", d: "After you fix something, who checks it went live, and whether anything improved?" },
];

export const FEATURES = [
  { slug: "audit", icon: "🔍", t: "Website SEO audit", d: "RankPilot crawls your pages the way a search engine would and lists what is holding them back, with the evidence for each finding and plain-language guidance on how to fix it.", bullets: ["Respects robots.txt and crawl limits", "Findings explained: what it means, why it matters, how to fix it", "Repeated problems from a shared template grouped into one"], shot: "findings" },
  { slug: "technical", icon: "🛠️", t: "Technical SEO intelligence", d: "Checks the things that decide whether search engines can find and understand your pages: indexability, canonicals, metadata, sitemaps, redirects, structured data, mobile setup and internal links.", bullets: ["Live homepage, redirect, robots.txt and sitemap checks", "Structured-data and social-tag checks", "Anything it could not test is marked “not tested”, never guessed"], shot: "intelligence" },
  { slug: "recommendations", icon: "✅", t: "AI SEO recommendations", d: "Turns findings and your Search Console data into a prioritised plan. AI drafts suggestions such as titles and descriptions, checks them against the facts on your page, and labels them as AI-generated.", bullets: ["One list across crawl, Search Console and AI ideas", "30-day plan sized to your website", "You approve before anything changes"], shot: "growth-plan" },
  { slug: "keywords", icon: "🧭", t: "Keyword intelligence", d: "Finds keyword and topic opportunities from your own pages and Search Console queries, groups them into topics, maps them to pages and flags overlaps between your own pages.", bullets: ["Every idea labelled: verified, AI estimate or not available", "Queries you almost rank for, ranked by opportunity", "Country-specific analysis for your target markets"], shot: "keywords" },
  { slug: "competitors", icon: "🥊", t: "Competitor analysis", d: "Reads public competitor pages and shows topics they cover that your titles and headings do not, plus how their page depth and structure compare with yours.", bullets: ["Public pages only", "No invented competitor traffic or rankings", "Topic gaps become content ideas"], shot: null },
  { slug: "content", icon: "✍️", t: "Content optimization", d: "Improve titles, meta descriptions, canonical tags, structured data and image alt text through approved changes, and see content depth, heading structure and trust-page checks for each site.", bullets: ["Approve, reject or edit every change", "Bulk approve and apply", "Before and after saved with rollback information"], shot: null },
  { slug: "gsc", icon: "📊", t: "Google Search Console integration", d: "Connect read-only to see real clicks, impressions, click-through rate, queries and average position, plus Google's own indexing status for your pages.", bullets: ["Read-only access", "Verified numbers, labelled as Google data", "Indexing status checked page by page"], shot: null },
  { slug: "ga4", icon: "📈", t: "Google Analytics integration", d: "Connect read-only to see organic landing-page sessions and engagement next to your search data, where Google Analytics 4 has data.", bullets: ["Read-only access", "Shown as engagement, not as a ranking measure", "Shown only when connected"], shot: null },
  { slug: "history", icon: "🕘", t: "SEO history and progress", d: "Your starting point is saved the first time a site is analysed and never overwritten. Later results are compared with it fairly, and a progress report you can share with a client is generated from the same data.", bullets: ["Permanent baseline", "Like-for-like comparisons, small numbers flagged", "Client-ready progress report"], shot: "history" },
  { slug: "validation", icon: "🛰️", t: "Recommendations and validation", d: "Track each recommendation from idea to applied change. After a change, RankPilot reads the live page and tells you whether it is really live, still being re-checked, or still showing the old value.", bullets: ["Live check after every change", "Statuses: pending, approved, applied, validated", "Kill switch to stop all writing"], shot: "overview" },
];

export const STEPS = [
  { t: "Add your website", d: "Create an account, add your site and verify that you own it. Optionally connect Google Search Console and Analytics, and tell RankPilot what your business offers.", icon: "1" },
  { t: "Analyze your SEO", d: "RankPilot crawls the site and checks technical, on-page, content and speed signals. You get a health score with the evidence behind it.", icon: "2" },
  { t: "Discover opportunities", d: "Findings, Search Console queries, keyword ideas and competitor gaps are combined into one list of opportunities.", icon: "3" },
  { t: "Review recommendations", d: "Each recommendation says what is wrong, why it matters, what to do and how it will be checked. You approve or reject it.", icon: "4" },
  { t: "Implement improvements", d: "Apply approved changes through a connected platform, or follow the exact instructions on any other site.", icon: "5" },
  { t: "Track your progress", d: "RankPilot confirms changes on the live page and compares results with your saved starting point over time.", icon: "6" },
];

export const AUDIENCES = [
  { t: "Small business owners", d: "Understand in plain language what is holding your site back and what to do next, without learning SEO jargon." },
  { t: "Agencies", d: "Run many client projects from one place and share a clear progress report that shows where each site started and what changed." },
  { t: "SEO professionals", d: "Skip the manual collation. Get evidence, history and a consistent workflow, and keep full control over what is applied." },
  { t: "Marketing teams", d: "Give everyone one prioritised list with owners, statuses and proof that work was completed." },
  { t: "E-commerce businesses", d: "Audit product and category pages for the same technical and on-page issues, with Shopify store support in beta." },
  { t: "Website owners", d: "Know whether your site is healthy, see which pages Google has indexed, and keep an eye on it over time." },
  { t: "Growing SaaS businesses", d: "Keep a fast-changing site crawlable and consistent as pages and content multiply." },
];

export const DIFFERENTIATORS = [
  { t: "Actionable recommendations", d: "Every finding comes with what to do, why, and how it will be verified." },
  { t: "Website-level intelligence", d: "Audit, search data, keywords and competitors are read together for your site, not in separate tools." },
  { t: "A continuous improvement loop", d: "Discover, analyze, plan, implement, validate, measure and improve, repeated as your site changes." },
  { t: "Historical progress visibility", d: "A permanent baseline and a comparison history show what actually changed." },
  { t: "First-party Google data", d: "Search Console and Analytics are connected read-only, so search numbers come from Google, not from estimates." },
  { t: "Data-source transparency", d: "Every number says whether it was verified, calculated by RankPilot, AI-generated or is not available." },
  { t: "AI-assisted, human-approved", d: "AI drafts and explains. You decide what is applied." },
  { t: "One unified workflow", d: "From first audit to client report, in the same place." },
];

export const INTEGRATIONS = [
  { n: "Google Search Console", d: "Clicks, impressions, CTR, queries, position and indexing status (read-only).", tag: "Live" },
  { n: "Google Analytics 4", d: "Organic landing-page sessions and engagement (read-only).", tag: "Live" },
  { n: "WordPress", d: "Apply approved titles, descriptions and more through an application password.", tag: "Live" },
  { n: "Webflow", d: "Apply approved on-page changes to your Webflow site.", tag: "Live" },
  { n: "Sanity", d: "Apply approved changes to content stored in Sanity.", tag: "Live" },
  { n: "GitHub", d: "Propose changes as pull requests for sites whose content lives in a repository.", tag: "Live" },
  { n: "Shopify", d: "Product and collection SEO for connected stores.", tag: "Beta" },
  { n: "Slack", d: "Notifications about crawls, regressions and approvals.", tag: "Live" },
];

export const FAQ: { q: string; a: string }[] = [
  { q: "What is RankPilot AI?", a: "RankPilot AI is an SEO platform that analyzes your website, finds what is holding it back in search, prepares recommended improvements for your approval, checks that changes went live, and tracks your progress over time." },
  { q: "How does RankPilot analyze my website?", a: "It crawls your public pages like a search engine would, respecting robots.txt and crawl limits, and checks titles, descriptions, headings, links, images, structured data, mobile setup, indexability and more. Every finding shows the evidence it was based on." },
  { q: "Do I need SEO experience?", a: "No. Each finding explains what it means, why it matters and how to fix it in plain language, and a 30-day plan puts the work in order. Experienced users can go straight to the evidence and history." },
  { q: "Can I connect Google Search Console?", a: "Yes. The connection is read-only. It unlocks real clicks, impressions, click-through rate, queries, average position and Google's indexing status for your pages, and powers keyword opportunities and progress tracking." },
  { q: "Can I connect Google Analytics?", a: "Yes. Connect Google Analytics 4 read-only to see organic landing-page sessions and engagement next to your search data. It is optional." },
  { q: "How does RankPilot generate recommendations?", a: "Rules check your crawl for known issues, your Search Console data shows where you almost rank, and AI helps draft wording and ideas. AI output is checked against the facts on your page and labelled as AI-generated, and nothing is applied without your approval." },
  { q: "Can I track SEO progress over time?", a: "Yes. RankPilot saves your starting point the first time it analyzes a site and compares later results with it, including health scores, issues fixed, and Search Console results when connected. A client-ready progress report is included." },
  { q: "Does RankPilot guarantee rankings?", a: "No. Rankings and traffic depend on search engines, competition, your website quality and how changes are implemented. RankPilot helps you find and fix what you can control, and shows honestly what changed." },
  { q: "Can I manage multiple projects?", a: "Yes. Each website is its own project with its own subscription, history and settings. You can add as many as you need." },
  { q: "What happens after the trial?", a: "If a plan includes a trial, its length and terms are shown with the plan before you pay. Trials are offered once per customer. You can cancel from the Billing page before the trial ends and you will not be charged." },
  { q: "Can I cancel my subscription?", a: "Yes, any time from the Billing page. After a paid period has started, access continues until the end of the period you paid for." },
];

const BRAND = "RankPilot AI";

export function pageMeta(o: { title: string; description: string; path: string }): Metadata {
  return {
    title: o.title,
    description: o.description,
    alternates: { canonical: o.path },
    openGraph: { title: `${o.title} | ${BRAND}`, description: o.description, url: o.path, siteName: BRAND, type: "website" },
    twitter: { card: "summary_large_image", title: `${o.title} | ${BRAND}`, description: o.description },
  };
}
