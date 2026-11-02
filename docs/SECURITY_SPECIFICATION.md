# RankPilot AI --- Security Specification

## 1. Security objectives

Protect customer websites, credentials, analytics data and tenant
information. Prevent unauthorized publishing, SSRF, cross-tenant access,
prompt injection and uncontrolled resource use.

## 2. Authentication and tenancy

-   Use secure sessions or short-lived tokens.
-   Enforce organization membership and role-based permissions
    server-side.
-   Apply tenant scoping to every database query and background job.
-   Require MFA for privileged roles when supported.
-   Log administrative and sensitive actions.

## 3. Secrets and integrations

-   OpenAI API key is supplied by the founder and must be stored only in
    server-side environment/secret storage.
-   Never commit secrets to repository or Markdown files.
-   Never expose secrets in frontend code, API responses, logs or error
    traces.
-   Encrypt OAuth/connector tokens at rest; restrict access and
    rotate/revoke on disconnect.
-   Request minimum scopes.
-   Separate development, staging and production credentials.

## 4. Crawler SSRF protection

-   Allow only HTTP/HTTPS.
-   Resolve and validate DNS results; block loopback, private,
    link-local, multicast and reserved ranges.
-   Revalidate after redirects and DNS changes.
-   Block cloud metadata endpoints.
-   Limit redirects, response sizes, decompression ratios, timeouts and
    content types.
-   Isolate browser rendering and restrict outbound network access where
    possible.

## 5. AI security

-   Treat website content and external data as untrusted.
-   Do not provide AI agents with credentials or direct tool access to
    publish.
-   Validate AI output against strict schemas and allowlisted
    operations.
-   Require deterministic policy evaluation before execution.
-   Prevent prompt injection from changing system policy or requesting
    secrets.

## 6. Publishing safeguards

-   Verify ownership and connector authorization.
-   Use least-privilege scopes.
-   Require approval for material/high-risk changes.
-   Store before/after states and audit records.
-   Validate after every write.
-   Pause automation after repeated validation failures.
-   Rollback only where a verified restoration mechanism exists.

## 7. Shared VPS safeguards

-   Run services under dedicated non-root users where practical.
-   Restrict file permissions and network ports.
-   Keep existing products isolated by users, directories, ports and
    Nginx routes.
-   Do not expose PostgreSQL or Redis publicly.
-   Configure firewall, SSH hardening, updates, backups and monitoring.
-   Avoid resource exhaustion through crawl concurrency, memory and disk
    quotas.
-   Keep secrets out of PM2 ecosystem files committed to source control;
    use protected environment injection.

## 8. Data lifecycle

Document retention for page snapshots, logs, AI traces, analytics and
reports. Provide customer export/deletion. Encrypt external backups and
periodically test restoration.
