"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  MeResponse,
  Website,
  WebsiteOverviewRow,
  confirmVerification,
  getMe,
  getOrganizationOverview,
  listWebsites,
  registerWebsite,
  startVerification,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import StatusBadge from "@/components/StatusBadge";
import styles from "./dashboard.module.css";

export default function DashboardPage() {
  const router = useRouter();
  const tokenRef = useRef<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [websites, setWebsites] = useState<Website[]>([]);
  const [overview, setOverview] = useState<Record<string, WebsiteOverviewRow>>({});
  const [error, setError] = useState<string | null>(null);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [pendingInstructions, setPendingInstructions] = useState<Record<string, string>>({});
  const [confirmTokens, setConfirmTokens] = useState<Record<string, string>>({});

  const organization = me?.organizations[0];

  const refreshWebsites = useCallback(
    async (activeToken: string, organizationId: string) => {
      const [sites, overviewRows] = await Promise.all([
        listWebsites(activeToken, organizationId),
        getOrganizationOverview(activeToken, organizationId),
      ]);
      setWebsites(sites);
      setOverview(Object.fromEntries(overviewRows.map((row) => [row.website_id, row])));
    },
    []
  );

  useEffect(() => {
    const activeToken = getToken();
    if (!activeToken) {
      router.push("/login");
      return;
    }
    tokenRef.current = activeToken;

    getMe(activeToken)
      .then(async (meResponse) => {
        setMe(meResponse);
        if (meResponse.organizations.length > 0) {
          await refreshWebsites(activeToken, meResponse.organizations[0].id);
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.push("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load dashboard.");
      });
  }, [router, refreshWebsites]);

  async function handleAddWebsite(event: React.FormEvent) {
    event.preventDefault();
    const token = tokenRef.current;
    if (!token || !organization) return;
    setError(null);
    try {
      await registerWebsite(token, organization.id, newUrl, newName);
      setNewUrl("");
      setNewName("");
      await refreshWebsites(token, organization.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add website.");
    }
  }

  async function handleStartVerification(websiteId: string) {
    const token = tokenRef.current;
    if (!token || !organization) return;
    try {
      const result = await startVerification(token, organization.id, websiteId);
      setPendingInstructions((prev) => ({ ...prev, [websiteId]: result.instructions }));
      await refreshWebsites(token, organization.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start verification.");
    }
  }

  async function handleConfirmVerification(websiteId: string) {
    const token = tokenRef.current;
    if (!token || !organization) return;
    const verificationToken = confirmTokens[websiteId];
    if (!verificationToken) return;
    try {
      await confirmVerification(token, organization.id, websiteId, verificationToken);
      await refreshWebsites(token, organization.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to confirm verification.");
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
        <div className={styles.header}>
          <div>
            <h1>Websites</h1>
            <p className={styles.subtitle}>{organization?.name ?? "Your workspace"}</p>
          </div>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}

        <div className={styles.card}>
          <h2>Add a website</h2>
          <form className={styles.addForm} onSubmit={handleAddWebsite}>
            <input
              type="url"
              placeholder="https://example.com"
              aria-label="https://example.com"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="Display name"
              aria-label="Display name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <button type="submit">Add website</button>
          </form>
        </div>

        <div className={styles.card}>
          <h2>Websites</h2>
          {websites.length === 0 && <p>No websites yet.</p>}
          {websites.map((site) => {
            const row = overview[site.id];
            return (
            <div key={site.id} className={styles.websiteRow}>
              <div className={styles.websiteRowHeader}>
                <Link href={`/dashboard/websites/${site.id}`}>
                  <strong>{site.display_name}</strong>
                </Link>
                <StatusBadge value={site.verification_status} />
                {row && <StatusBadge value={row.status} />}
              </div>
              <span>{site.canonical_url}</span>
              {row && (
                <span className={styles.subtitle}>
                  {row.open_findings_count} findings · {row.open_opportunities_count} opportunities ·{" "}
                  {row.pending_tasks_count} pending tasks · last crawl: {row.last_crawl_status ?? "never"}
                </span>
              )}

              {site.verification_status !== "verified" && (
                <div className={styles.verifyActions}>
                  <button onClick={() => handleStartVerification(site.id)}>
                    Get verification instructions
                  </button>
                  <input
                    type="text"
                    placeholder="Paste token to confirm"
                    aria-label="Paste token to confirm"
                    value={confirmTokens[site.id] ?? ""}
                    onChange={(e) =>
                      setConfirmTokens((prev) => ({ ...prev, [site.id]: e.target.value }))
                    }
                  />
                  <button onClick={() => handleConfirmVerification(site.id)}>
                    Confirm verification
                  </button>
                </div>
              )}

              {pendingInstructions[site.id] && (
                <p className={styles.instructions}>{pendingInstructions[site.id]}</p>
              )}
            </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
