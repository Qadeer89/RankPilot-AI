# RankPilot AI --- AI Agent Specification

## 1. Purpose

AI agents turn evidence from the crawler, SEO rules and authorized
analytics into prioritized explanations and safe proposals. Agents are
bounded workers, not unrestricted autonomous operators.

## 2. MVP agents

1.  **SEO Opportunity Analyst:** ranks findings and Search Console
    observations by impact, confidence, effort and risk.
2.  **Content Optimization Agent:** proposes page-specific title,
    description, heading and content improvements using supplied page
    content and customer context.
3.  **Internal Linking Analyst:** identifies relevant source/target page
    candidates from the crawled site graph.
4.  **SEO Strategy Assistant:** produces a weekly action plan and
    explains trade-offs.
5.  **Execution Planner:** converts an approved opportunity into typed
    connector operations.
6.  **Post-change QA Assistant:** summarizes deterministic validation
    evidence; it cannot declare success when checks fail.

The crawler, rule engine, scheduler and execution service are
conventional software components, not LLM agents.

## 3. OpenAI integration

The founder already has an OpenAI API key. Use that account for MVP
inference: - Keep the key server-side in environment variables or a
secret manager. - Never commit it to Git, include it in Markdown, send
it to the browser or print it in logs. - Support model configuration
through environment settings. - Use structured outputs/JSON schema where
supported. - Set per-tenant and global token/cost limits. - Retry
transient failures with bounded exponential backoff. - Record model,
token usage, latency and estimated cost. - Do not assume the ChatGPT
subscription includes API credits; API billing is separate and must be
checked in the OpenAI platform account.

## 4. Input and output contract

Every agent input must include: - Tenant and website IDs. - Task purpose
and allowed scope. - Relevant page/finding/search evidence. - Data
freshness and source labels. - Risk policy and allowed operations. -
Token/response budget.

Every output must include: - Summary. - Evidence references. -
Confidence and uncertainty. - Recommended action. - Expected benefit
hypothesis (not guarantee). - Risk tier. - Approval requirement. -
Validation plan. - Structured machine-readable operation proposal, if
applicable.

## 5. AI vs deterministic logic

Use deterministic code for: - HTTP status and redirect checks. -
Canonical and robots directive parsing. - Sitemap membership. -
Missing/duplicate metadata detection. - Structured data
parsing/validation signals. - Link status and crawl constraints. -
Permission checks, approval rules and execution authorization.

Use AI for: - Explaining findings in plain language. - Clustering
related opportunities. - Drafting metadata/content proposals. -
Relevance assessment for internal links. - Summarizing weekly outcomes
and uncertainty.

## 6. Prompt injection and untrusted content

Treat all crawled content, page source, metadata, schema, comments and
external documents as untrusted data. They must never override
system/developer instructions or request secrets/actions. Strip or
isolate irrelevant instructions and pass only necessary excerpts. The AI
must not receive write credentials.

## 7. Cost controls

-   Run deterministic checks before invoking AI.
-   Deduplicate by content hash and finding state.
-   Analyze only changed or high-value pages.
-   Use smaller/cheaper models for classification and summaries where
    quality is adequate.
-   Limit page text, context size, output tokens and retries.
-   Cache stable results.
-   Set per-site daily AI budgets and global kill switch.
-   Log token usage and estimated cost by organization/site/task.

## 8. Evaluation

Maintain a golden dataset from the founder's own websites. Human-review
proposed changes for correctness, search intent, brand voice,
factuality, duplication, risk and usefulness. Track false positives,
accepted proposals, rejected proposals, post-change validation and cost
per accepted improvement.
