# RankPilot AI — Operational Runbooks

Covers RP-0906 (`docs/DEVELOPMENT_TASKS.md`) and the backup/restore and incident-response
requirements in `docs/SECURITY_SPECIFICATION.md` #7–#8. These procedures have **not been run
against a real production host** — this development environment has no VPS to run them
against. Before going live, run every procedure here once for real, on the actual host, and
record the date and result at the bottom of this file. Treat an unverified backup as having a
100% chance of being broken: a backup earns trust from a restore that worked, not from a
`pg_dump` that returned exit code 0.

## 1. Backup

### 1.1 What gets backed up

- The `rankpilot` Postgres database (all application data).
- `apps/api/.env` (environment configuration) — **back this up separately, encrypted, and
  never in the same place as the database dump**: it contains the token-encryption key, which
  is itself the thing protecting the OAuth/connector secrets stored in the database. Losing
  the `.env` backup while keeping the database backup means the stored tokens become
  permanently undecryptable; that's an acceptable outcome (force reconnection), but losing both
  the database backup and the ability to reach the host is not.

### 1.2 Database backup command

```bash
# Run as the rankpilot app user, or any user with SELECT on the database.
PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h localhost -U rankpilot -d rankpilot \
  --format=custom \
  --file="/tmp/rankpilot-$(date +%Y%m%d-%H%M%S).dump"
```

Then **encrypt and ship it off the VPS** — a backup stored only on the machine it protects
against is not a backup (`SECURITY_SPECIFICATION.md` #7: "Configure firewall, SSH hardening,
updates, backups and monitoring" and #8: "Encrypt external backups"):

```bash
gpg --symmetric --cipher-algo AES256 --output rankpilot-backup.dump.gpg rankpilot-*.dump
# Upload rankpilot-backup.dump.gpg to off-host storage (object storage bucket, another
# machine) that isn't reachable with the same credentials as the VPS itself.
rm rankpilot-*.dump  # don't leave the unencrypted dump behind
```

### 1.3 Schedule

Run the backup daily, after the retention-cleanup job (`run_retention_cleanup`, scheduled at
03:00 UTC in `apps/api/app/celery_app.py`) so the backup reflects post-cleanup state — schedule
the backup for 03:30 UTC or later. This is not yet automated as a Celery task: for the founder
pilot, a plain cron entry calling the script above is sufficient; revisit once there's a
dedicated ops/infra owner.

## 2. Restore

### 2.1 Restore procedure

```bash
gpg --decrypt rankpilot-backup.dump.gpg > rankpilot-restore.dump

# Restore into a FRESH database, never directly over the live one, so a bad
# backup can't take down what's currently running:
createdb -h localhost -U postgres rankpilot_restore_test
PGPASSWORD="$DB_PASSWORD" pg_restore \
  -h localhost -U rankpilot -d rankpilot_restore_test \
  --no-owner --no-privileges \
  rankpilot-restore.dump
```

### 2.2 Restore verification checklist

After restoring into `rankpilot_restore_test`, confirm — don't just confirm the command
exited 0:

```sql
SELECT count(*) FROM organizations;
SELECT count(*) FROM websites;
SELECT count(*) FROM seo_findings WHERE status = 'open';
SELECT count(*) FROM change_records;
```

Compare counts against what you expect from the backup's timestamp. Then point a throwaway
copy of the API (different port, `RANKPILOT_DATABASE_URL` pointed at
`rankpilot_restore_test`) at it and confirm `GET /api/v1/health` and `GET /api/v1/ready` both
pass, and that `alembic current` matches the migration head in `apps/api/migrations/versions/`
— a restore from before the latest migration needs `alembic upgrade head` run against it
before it's usable.

```bash
dropdb -h localhost -U postgres rankpilot_restore_test   # clean up afterward
```

### 2.3 Restore cadence

Test a real restore at least monthly, and immediately before any migration that touches a
large or sensitive table. An untested backup is not a backup.

## 3. Incident response

### 3.1 Global kill switch

Three independent levers, in order of how fast each one acts:

1. **Stop the worker from executing anything new**: `pm2 stop rankpilot-worker` — in-flight
   tasks finish, no new ones start.
2. **Stop new crawls/writes from being scheduled at all**: `pm2 stop rankpilot-scheduler`
   (Celery beat). Combine with step 1 for a full stop.
3. **Pause one specific website** (far more common than a global stop): `POST
   /api/v1/organizations/{organization_id}/websites/{website_id}/pause`. Every entry point
   into `app/execution/service.py` checks `website.status == WebsiteStatus.active` before
   doing anything, so this blocks writes to that site without affecting any other site.

There is deliberately no single global "automation off" database flag yet — pausing is
per-website. If every website needs to stop at once, use levers 1–2.

### 3.2 "A bad change was executed on a customer's site"

1. Find the `ChangeRecord`: `GET
   /api/v1/organizations/{org}/websites/{website}/change-records/{id}`. Check
   `validation_status` — if it's `failed`, a rollback was already attempted automatically
   (`app/execution/service.py`'s `execute_task`); check for a `RollbackRecord` on that change
   before doing anything manually.
2. If no rollback exists or it failed: `POST .../change-records/{id}/rollback`. This only
   works for the operations the WordPress connector actually supports restoring
   (`set_title`, `set_meta_description`) — see `app/connectors/wordpress.py`. If the
   connector can't restore the prior state, say so to the customer; never claim a rollback
   succeeded when `RollbackRecord.status` is `failed` or `unavailable`.
3. Pause the website (3.1, lever 3) while investigating.
4. Check `agent_runs` and `seo_tasks` for the chain that produced the change: which
   `SEOOpportunity`, which `OpportunityProposal`, who approved it (`approvals.decided_by`).

### 3.3 "The AI is producing bad proposals" / suspected prompt injection

1. Pull the `AgentRun` rows for the website/time window in question and the `SEOTask.
   proposed_change_json` they produced.
2. Confirm whether anything actually executed: `execute_task` re-validates risk tier and
   approval status from the database, never from what the AI claimed
   (`app/execution/policy.py` — see also the dedicated tests in
   `apps/api/tests/test_ai_content_agent.py` for the allowlist defense). A model being fooled
   by injected page content should, at worst, produce a *rejected* or *never-approved* task —
   if something executed that shouldn't have, treat it as a policy bug, not an AI behavior
   issue, and follow 3.2.
3. If the daily AI budget (`RANKPILOT_AI_DAILY_BUDGET_USD_PER_SITE`) is being exhausted
   unexpectedly, check `agent_runs.estimated_cost` for the site/day — `app/ai/budget.py`
   enforces the ceiling before every call, so budget exhaustion blocks further calls rather
   than overspending silently.

### 3.4 "Celery queue is backed up" / crawls not running

1. `pm2 logs rankpilot-worker` — the worker runs at `--concurrency 1` by design
   (`SYSTEM_ARCHITECTURE.md` #6); a single slow or stuck crawl blocks everything behind it.
2. Check Redis is reachable (`redis-cli ping`) and not out of memory.
3. If a specific crawl is stuck, there's no task-cancellation endpoint yet — restart the
   worker (`pm2 restart rankpilot-worker`); an in-progress crawl's `CrawlJob` row is left in
   `running` status and should be manually marked `failed` if it's not going to resume (no
   automatic timeout/reaper exists yet — a gap worth closing before scaling beyond the founder
   pilot).

### 3.5 "Disk is full" / suspected unbounded growth

Page snapshots are the only place raw-ish crawled content accumulates
(`app/tasks/retention.py` deletes them past `RANKPILOT_PAGE_SNAPSHOT_RETENTION_DAYS`, 90 days
by default). If retention cleanup isn't running (check `rankpilot-scheduler` is up, per 3.1),
that's the first thing to fix, not a manual `DELETE`.

### 3.6 "A secret may have leaked" (API key, OAuth token, WordPress Application Password)

1. Rotate at the source immediately: revoke the OpenAI key in the OpenAI platform console,
   revoke the Google OAuth client secret in Google Cloud Console, revoke the WordPress
   Application Password on the WordPress site itself (Users → Profile → Application
   Passwords).
2. Update the corresponding `RANKPILOT_*` environment variable on the host and restart every
   PM2 process (`pm2 restart all`) — stale env vars persist in already-running processes.
3. If `RANKPILOT_TOKEN_ENCRYPTION_KEY` itself may have leaked, rotating it invalidates every
   stored `oauth_connections` / `website_connections` row (they become permanently
   undecryptable with the old key); every customer will need to reconnect. This is the correct
   trade-off — don't try to "re-encrypt in place" under suspicion of compromise.

## 4. Verification log

Record every real run of section 1 or 2 here. An empty table below means these procedures
have only been specified, never executed.

| Date | Procedure | Result | Notes |
|------|-----------|--------|-------|
| _(none yet)_ | | | |
