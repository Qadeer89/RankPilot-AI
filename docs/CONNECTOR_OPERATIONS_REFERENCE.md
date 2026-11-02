# RankPilot AI — Connector Operations Reference (RP13-016)

This is the exact, code-grounded reference for what each write connector
can and cannot do: supported operations, the live mapping to each
provider's real API, required OAuth/API scopes, rollback capability, and
known limitations. It supersedes the narrative description in
`WEBSITE_CONNECTORS.md` wherever the two disagree, per
`RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md`'s source-of-truth
hierarchy (code and tests first).

A connector's write access is never implied by domain verification alone
(`SECURITY_SPECIFICATION.md` #6). Every operation below runs only through
the risk-tier/approval pipeline in `app/execution/service.py`, with
before/after state capture and deterministic post-change validation.

## Shared operation vocabulary

All four connectors implement the same two operations, so the execution
engine's risk-tier, approval, and rollback logic doesn't need to know
which connector it's talking to:

| Operation | Meaning |
|---|---|
| `set_title` | Set the page/resource's `<title>` (SEO title tag) |
| `set_meta_description` | Set the page/resource's meta description |

No connector supports any other operation today (no delete, no
permalink/URL changes, no template/theme changes, no robots/indexability
changes, no bulk/mass operations) — consistent with
`WEBSITE_CONNECTORS.md` #3's MVP restriction.

---

## WordPress (`app/connectors/wordpress.py`)

**Auth:** a dedicated WordPress Application Password (never the site
owner's main login). Credentials: `(site_url, username, application_password)`.

**Granted scopes recorded:** `["read", "edit_posts"]`
(`app/execution/connections.py::connect_wordpress`).

| Operation | Live API call | Reliability |
|---|---|---|
| `set_title` | `POST /wp-json/wp/v2/{pages\|posts}/{id}` with `{"title": ...}` | Reliable — core WordPress REST field |
| `set_meta_description` | Same endpoint, `{"meta": {"_yoast_wpseo_metadesc": ...}}` | **Best-effort** — raises `UnsupportedOperation` if the site doesn't expose a Yoast-SEO-compatible meta key, or if WordPress silently accepted but didn't persist the value |

**Target resolution:** `find_post_by_url` matches the target URL's slug
against `pages` then `posts` (first match wins).

**Rollback:** re-applies the captured before-value via the same
operation (`update_title`/`update_meta_description`). Fully tested
(`tests/test_wordpress_connector.py`, `tests/test_execution_service.py`).

**Known limitation:** a site with duplicate slugs across pages/posts
resolves to whichever is found first; not disambiguated further.

---

## Shopify (`app/connectors/shopify.py`)

**Auth:** a Shopify Admin API access token scoped to one store (custom
app token — never the merchant's own login). Credentials:
`(shop_domain, access_token)`.

**Granted scopes recorded:**
`["read_content", "write_content", "read_products", "write_products"]`
(`app/execution/connections.py::connect_shopify`). Both resource-type
scope pairs are required because `find_target` searches pages *and*
products (`RESOURCE_TYPES_TO_SEARCH`); `write_content` alone does not
cover product metafields, and `write_products` alone does not cover page
metafields.

| Operation | Live API call | Reliability |
|---|---|---|
| `set_title` | Metafield `global.title_tag` (namespace `global`, key `title_tag`) on the matched page or product | Reliable — the field Shopify's own "Edit website SEO" admin panel writes |
| `set_meta_description` | Metafield `global.description_tag` | Reliable, same mechanism |

Deliberately **not** the product/page's own `title` field: that's the
resource's display name, and writing it would rename the product, not
just its SEO `<title>` tag.

**Target resolution:** `find_target` matches the target URL's last path
segment against each resource type's `handle` field, pages first.

**Rollback:** re-applies the captured before-value via `apply_change`
(the same metafield write). Tested in `tests/test_shopify_connector.py`,
`tests/test_execution_service_generic_connectors.py`.

**Known limitation:** not yet exercised against a live Shopify store
from this environment (no credential available) — implemented and
unit-tested against the documented Admin REST API shape only.

---

## Webflow (`app/connectors/webflow.py`)

**Auth:** a Webflow site API token (Site Settings → Apps & Integrations)
or an OAuth app token with the `pages:write` scope. Credentials:
`(site_id, access_token)`.

**Granted scopes recorded:** `["pages:read", "pages:write"]`
(`app/execution/connections.py::connect_webflow`).

| Operation | Live API call | Reliability |
|---|---|---|
| `set_title` | `PATCH /v2/pages/{page_id}` with `{"title": ...}` (Data API v2 Pages resource) | Reliable per the documented v2 schema |
| `set_meta_description` | Same endpoint, `{"seo": {"description": ...}}` | Reliable per the documented v2 schema; raises `UnsupportedOperation` on an HTTP 400 |

**Target resolution:** `find_target` lists the site's pages and matches
by `slug` against the target URL's last path segment.

**Rollback:** re-applies the captured before-value via `apply_change`.
Tested in `tests/test_webflow_connector.py`,
`tests/test_execution_service_generic_connectors.py`.

**Known limitation:** same as Shopify — not yet exercised against a live
Webflow site from this environment; implemented and unit-tested against
the documented API shape only. Only covers Webflow's *Pages* resource,
not CMS Collection Items.

---

## GitHub (custom-code sites, `app/connectors/github_pr.py`)

**Auth:** a GitHub personal access token scoped to one repository (never
a broad org-wide token). Credentials: `(owner, repo, base_branch, access_token)`.

**Granted scopes recorded:** `["contents:write", "pull_requests:write"]`
(`app/execution/connections.py::connect_github`).

This connector is fundamentally different from the other three: a
custom-code site has no live write API, so it **never writes live**. Its
one write action is opening a branch + commit + pull request with the
proposed change, for a human to review and merge.

| Operation | What actually happens | Reliability |
|---|---|---|
| `set_title` | Regex-replaces the `<title>...</title>` block in the resolved source file, commits to a new branch, opens a PR | Only works if the file has an existing `<title>` tag; raises `UnsupportedOperation` otherwise |
| `set_meta_description` | Regex-replaces the `<meta name="description" content="...">` tag, same commit/PR flow | Only works if the file has an existing meta description tag |

**Target resolution:** `find_target` tries a small set of conventional
static-site paths derived from the URL (e.g. `/about/` → `about.html`,
`about/index.html`, `pages/about.html`, `public/about.html`,
`src/pages/about.html`). A site that doesn't follow one of these
conventions isn't supported — there is no fallback.

**Validation:** deliberately shallower than the live connectors — it
confirms the PR is open and its branch's file content contains the
expected value, not that a deployed site actually serves it. This
platform has no way to observe a deploy pipeline it doesn't control.
This is a documented limitation, not an oversight.

**Rollback:** closes the still-open PR (`close_pull_request`) rather than
reverting a live change, since nothing has shipped. Once a PR merges,
reverting is an ordinary git operation outside this platform's scope.

Tested in `tests/test_github_pr_connector.py`,
`tests/test_execution_service_generic_connectors.py`.

---

## Cross-cutting guarantees (all four connectors)

- **Credentials never reach the AI.** Proposals are generated from
  evidence only; execution happens through `app/execution/service.py`,
  which the AI has no path into (`SECURITY_SPECIFICATION.md` #5).
- **Credentials are encrypted at rest** (`app/core/encryption.py`), never
  logged, never returned in an API response — only `config_json`'s
  non-secret fields (shop domain, site id, repo/branch) are ever exposed
  to the frontend (`WebsiteConnectionResponse`).
- **Connect-time verification:** every `connect_*` function calls the
  connector's `verify_credentials` against the live API before storing
  anything; a `ConnectorError` (including a network-level failure —
  RP13-007's `safe_request` fix) becomes a clean `400`, never a stored,
  unverified credential.
- **Disconnect/revocation:** every connector has a `disconnect_*`
  function (`app/execution/connections.py`) that marks the
  `WebsiteConnection` row `disconnected`; the encrypted secret is not
  deleted (so re-connecting with the same scopes is cheap) but is never
  used again while disconnected.
- **One live connector per website, by priority:** if more than one
  connector is somehow connected at once, `get_connected_content_connector`
  picks WordPress > Shopify > Webflow > GitHub, deterministically.
