"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  MeResponse,
  Website,
  confirmVerification,
  getMe,
  listWebsites,
  registerWebsite,
  startVerification,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import styles from "./dashboard.module.css";

function statusClassName(status: string): string {
  if (status === "verified") return `${styles.statusBadge} ${styles.statusVerified}`;
  if (status === "failed") return `${styles.statusBadge} ${styles.statusFailed}`;
  return styles.statusBadge;
}

export default function DashboardPage() {
  const router = useRouter();
  const tokenRef = useRef<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [websites, setWebsites] = useState<Website[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [pendingInstructions, setPendingInstructions] = useState<Record<string, string>>({});
  const [confirmTokens, setConfirmTokens] = useState<Record<string, string>>({});

  const organization = me?.organizations[0];

  const refreshWebsites = useCallback(
    async (activeToken: string, organizationId: string) => {
      const sites = await listWebsites(activeToken, organizationId);
      setWebsites(sites);
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
          {error ? <p className={styles.error}>{error}</p> : <p>Loading...</p>}
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

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.card}>
          <h2>Add a website</h2>
          <form className={styles.addForm} onSubmit={handleAddWebsite}>
            <input
              type="url"
              placeholder="https://example.com"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="Display name"
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
          {websites.map((site) => (
            <div key={site.id} className={styles.websiteRow}>
              <div className={styles.websiteRowHeader}>
                <Link href={`/dashboard/websites/${site.id}`}>
                  <strong>{site.display_name}</strong>
                </Link>
                <span className={statusClassName(site.verification_status)}>
                  {site.verification_status}
                </span>
              </div>
              <span>{site.canonical_url}</span>

              {site.verification_status !== "verified" && (
                <div className={styles.verifyActions}>
                  <button onClick={() => handleStartVerification(site.id)}>
                    Get verification instructions
                  </button>
                  <input
                    type="text"
                    placeholder="Paste token to confirm"
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
          ))}
        </div>
      </div>
    </div>
  );
}
