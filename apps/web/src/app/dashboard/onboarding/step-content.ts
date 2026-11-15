// Explanatory copy for each guided-setup step (Part 2 of the onboarding
// spec). Describes only what RankPilot AI actually implements today --
// see docs/CONNECTOR_OPERATIONS_REFERENCE.md and docs/USER_ONBOARDING.md
// for the source of truth this mirrors.

export interface StepContent {
  heading: string;
  body: string[];
  actionLabel: string;
  actionHref: string;
}

export const STEP_CONTENT: Record<string, StepContent> = {
  welcome: {
    heading: "Welcome to RankPilot AI",
    body: [
      "RankPilot AI crawls your website, finds real SEO issues, and can draft and -- if you allow it -- publish fixes automatically.",
      "You'll add a website, verify you own it, optionally connect your CMS and Google accounts, run your first audit, and choose how much RankPilot is allowed to change on its own.",
    ],
    actionLabel: "Start setup",
    actionHref: "/dashboard",
  },
  add_website: {
    heading: "Add your website",
    body: [
      "Enter your website's URL on the dashboard. RankPilot creates a project for it and checks the URL is safe to crawl before doing anything else.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  verify_website: {
    heading: "Verify website ownership",
    body: [
      "Before RankPilot will monitor or change anything, you prove you actually control the site -- currently via an HTML file placed at a specific path.",
      "This prevents someone from registering a website they don't own and having RankPilot act on it.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  connect_cms: {
    heading: "Connect your CMS (optional)",
    body: [
      "Connecting a CMS lets RankPilot actually publish approved fixes, not just report them.",
      "WordPress: title, meta description, image alt text, and canonical URL.",
      "Shopify, Webflow, Sanity: title and meta description.",
      "GitHub (for custom-code sites): title, meta description, canonical URL, and schema markup -- opened as a pull request for a human to review and merge, since there's no live write API for custom code.",
      "You can skip this and use RankPilot in audit-only mode if you'd rather apply fixes yourself.",
    ],
    actionLabel: "Go to Integrations",
    actionHref: "/dashboard",
  },
  connect_gsc: {
    heading: "Connect Google Search Console (optional)",
    body: [
      "Search Console gives RankPilot real search performance data: clicks, impressions, CTR, average position, and per-query data, plus Google's own indexing status for specific URLs.",
      "This is how RankPilot can tell you a page's rankings actually declined, instead of guessing from the crawl alone.",
    ],
    actionLabel: "Go to Integrations",
    actionHref: "/dashboard",
  },
  connect_ga4: {
    heading: "Connect Google Analytics 4 (optional)",
    body: [
      "GA4 adds traffic and engagement context alongside Search Console's ranking data.",
      "Entirely optional -- RankPilot's core audit and fix engine works without it.",
    ],
    actionLabel: "Go to Integrations",
    actionHref: "/dashboard",
  },
  configure_crawling: {
    heading: "Configure website crawling",
    body: [
      "RankPilot discovers your pages via your sitemap (falling back to link-following if none exists), respects robots.txt, and can render JavaScript-heavy pages where needed.",
      "You control how often it re-crawls and how many pages it's allowed to touch per run.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  first_audit: {
    heading: "Run your first SEO audit",
    body: [
      "Starting a crawl runs RankPilot's full rule engine against every page it discovers -- technical SEO, on-page SEO, content, images, and more.",
      "You'll see pages discovered, crawled, and analyzed, and the issues found, as the audit progresses.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  review_findings: {
    heading: "Understand your SEO findings",
    body: [
      "Findings are graded critical, warning, or passed. Each one explains what's wrong, why it matters, and (where RankPilot can fix it) what the proposed change would be.",
      "Opportunities are a step up from a single finding -- a prioritized, estimated-impact recommendation RankPilot thinks is worth acting on.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  ai_optimization: {
    heading: "Configure AI optimization (optional)",
    body: [
      "RankPilot's AI can draft: page titles, meta descriptions, image alt text, canonical URLs, and (on supported connectors) schema markup and heading-hierarchy recommendations.",
      "A draft is never the same as a published change -- it only goes live once it's approved (manually, or automatically under Autopilot for low-risk categories you've opted in to).",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  automation_mode: {
    heading: "Choose an automation mode",
    body: [
      "Audit -- RankPilot only reports issues. It never drafts or publishes a change.",
      "Copilot -- RankPilot drafts fixes and proposes them, but every change needs your explicit approval before it's applied.",
      "Autopilot -- Low-risk categories you've opted in to are applied automatically, validated against the live page afterward, and rolled back if validation fails. Higher-risk changes still require approval.",
      "Nothing is ever applied automatically unless you've explicitly chosen Autopilot and opted that category in.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  notifications: {
    heading: "Configure notifications (optional)",
    body: [
      "RankPilot can notify you by email when: a previously-passing check regresses, a scheduled auto-pipeline run finishes, a fix fails validation, or a crawl fails.",
      "Only the notification types actually wired up in this deployment are shown on the website settings page.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
  explore_dashboard: {
    heading: "Explore your dashboard",
    body: [
      "Your SEO Health Score, crawl history, recent changes, pending tasks, and reports all live on your website's detail page.",
      "This is the last step -- once you've had a look around, setup is complete.",
    ],
    actionLabel: "Go to dashboard",
    actionHref: "/dashboard",
  },
};
