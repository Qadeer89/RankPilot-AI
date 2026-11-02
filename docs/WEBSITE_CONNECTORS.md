# RankPilot AI --- Website Connector Specification

## 1. Connector model

Separate capabilities into: - **Public crawler:** read-only access to
public pages. - **Verification connector:** proves domain control. -
**Analytics connector:** authorized read access to Search Console/GA4. -
**Write connector:** authorized publishing/modification capability.

A website URL alone never grants write permission.

## 2. Universal crawler

Responsibilities: - Normalize and validate URLs. - Respect robots.txt
and configured crawl policies. - Discover XML sitemaps. - Crawl within
page, depth, rate and time budgets. - Extract status, redirects, title,
description, canonical, robots, headings, schema and internal links. -
Detect duplicate content fingerprints. - Use browser rendering only when
static fetching is insufficient.

Safety: - Block private, loopback, link-local and cloud metadata IP
ranges. - Re-check DNS and redirects to prevent SSRF. - Restrict schemes
to HTTP/HTTPS. - Apply per-host rate limits and timeouts. - Do not fetch
arbitrary local files or internal services.

## 3. WordPress connector --- first write connector

Connection: - Prefer a dedicated least-privilege application account or
secure plugin/API mechanism. - Use TLS and scoped credentials. - Verify
site identity and connector permissions. - Support
disconnect/revocation.

Initial operations: - Read pages/posts and metadata. - Update page title
and meta description where supported. - Update selected content fields
only with explicit policy. - Read back and validate every update.

Do not perform mass publishing, delete content, change permalink
structure, alter global templates or modify robots/indexability settings
automatically in MVP.

## 4. Founder-owned pilot websites

The founder's own websites are the first validation properties. For
each: - Confirm ownership and permitted test scope. - Record baseline
crawl and Search Console property if available. - Identify production vs
staging environment. - Prefer staging for risky execution tests. - Keep
a manual snapshot/backup before write tests. - Start in read-only mode;
enable writes only after connector verification.

## 5. Custom-code websites

For custom websites, MVP supports public crawling and recommendations.
Publishing can be enabled later through a GitHub/deployment connector
with explicit repository and deployment permissions. GitHub integration
is P1 unless one of the pilot sites requires it to validate the product.

## 6. Future connectors

Possible future adapters: - Shopify - Webflow - GitLab/Bitbucket -
Custom CMS APIs - Additional analytics/search data sources

Do not commit to universal write support at launch. Every connector must
declare supported operations, scopes, rollback capability and validation
methods.
