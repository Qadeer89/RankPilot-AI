"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  MeResponse,
  WebsiteOverviewRow,
  getMe,
  getOrganizationOverview,
  sendSlackTestNotification,
  updateOrganizationSettings,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import styles from "./organization.module.css";

function badgeClass(value: string | null): string {
  const good = ["verified", "active", "completed"];
  const bad = ["failed", "error", "paused"];
  if (!value) return styles.badge;
  if (good.includes(value)) return `${styles.badge} ${styles.badgeGood}`;
  if (bad.includes(value)) return `${styles.badge} ${styles.badgeBad}`;
  return `${styles.badge} ${styles.badgeWarn}`;
}

export default function OrganizationSettingsPage() {
  const router = useRouter();
  const tokenRef = useRef<string | null>(null);

  const [me, setMe] = useState<MeResponse | null>(null);
  const [overview, setOverview] = useState<WebsiteOverviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [slackWebhookUrl, setSlackWebhookUrl] = useState("");

  const organization = me?.organizations[0];

  const refreshOverview = useCallback(async (token: string, organizationId: string) => {
    setOverview(await getOrganizationOverview(token, organizationId));
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    tokenRef.current = token;

    getMe(token)
      .then(async (meResponse) => {
        setMe(meResponse);
        if (meResponse.organizations.length > 0) {
          await refreshOverview(token, meResponse.organizations[0].id);
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.push("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load organization.");
      });
  }, [router, refreshOverview]);

  async function handleSaveSlackWebhook(event: React.FormEvent) {
    event.preventDefault();
    const token = tokenRef.current;
    if (!token || !organization) return;
    setError(null);
    setNotice(null);
    try {
      await updateOrganizationSettings(token, organization.id, {
        slack_webhook_url: slackWebhookUrl || null,
      });
      setNotice("Slack webhook saved.");
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to save Slack webhook.");
    }
  }

  async function handleSendSlackTest() {
    const token = tokenRef.current;
    if (!token || !organization) return;
    setError(null);
    setNotice(null);
    try {
      const result = await sendSlackTestNotification(token, organization.id);
      setNotice(`Test notification ${result.status}.`);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to send test notification.");
    }
  }

  if (!me) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>
          {error ? <p className={styles.error} role="alert">{error}</p> : <p>Loading...</p>}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Link className={styles.backLink} href="/dashboard">
          ← Back to dashboard
        </Link>

        <div className={styles.header}>
          <h1>{organization?.name ?? "Organization"}</h1>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}
        {notice && <p className={styles.success}>{notice}</p>}

        <div className={styles.card}>
          <h2>Agency overview</h2>
          <p className={styles.rowMeta}>
            One row per client website — status, open findings/opportunities, and pending tasks, so an
            agency can triage which sites need attention without opening each one.
          </p>
          {overview.length === 0 && <p className={styles.empty}>No websites yet.</p>}
          {overview.map((row) => (
            <Link key={row.website_id} href={`/dashboard/websites/${row.website_id}`} className={styles.row}>
              <div className={styles.rowMain}>
                <span>{row.display_name}</span>
                <span className={styles.rowMeta}>{row.hostname}</span>
              </div>
              <div className={styles.actions}>
                <span className={badgeClass(row.verification_status)}>{row.verification_status}</span>
                <span className={badgeClass(row.status)}>{row.status}</span>
                <span className={styles.rowMeta}>
                  {row.open_findings_count} findings · {row.open_opportunities_count} opportunities ·{" "}
                  {row.pending_tasks_count} pending tasks
                </span>
                <span className={styles.rowMeta}>
                  last crawl: {row.last_crawl_status ?? "never"}
                </span>
              </div>
            </Link>
          ))}
        </div>

        <div className={styles.card}>
          <h2>Slack notifications</h2>
          <p className={styles.rowMeta}>
            Add an incoming webhook URL to get notifications in your own Slack channel. Unconfigured, no
            Slack notifications are sent — nothing breaks.
          </p>
          <form className={styles.actions} onSubmit={handleSaveSlackWebhook}>
            <input
              className={styles.input}
              type="url"
              placeholder="https://hooks.slack.com/services/..."
              aria-label="https://hooks.slack.com/services/..."
              value={slackWebhookUrl}
              onChange={(e) => setSlackWebhookUrl(e.target.value)}
            />
            <button className={`${styles.button} ${styles.buttonPrimary}`} type="submit">
              Save
            </button>
            <button className={styles.button} type="button" onClick={handleSendSlackTest}>
              Send test notification
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
