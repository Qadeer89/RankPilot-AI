"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, MeResponse, getMe, sendVerificationEmail } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  AiCostsSection, AuditSection, HealthSection, OverviewSection, PaymentsSection, ProjectsSection, ReplacementsSection,
  RevenueSection, SettingsSection, SubscriptionsSection, TrialsSection, UsersSection, WebhooksSection,
} from "./sections";
import type { RangeValue } from "./parts";
import styles from "./admin.module.css";

const TABS = [
  ["overview", "Overview"], ["users", "Users"], ["projects", "Projects"], ["subscriptions", "Subscriptions"], ["payments", "Payments"],
  ["revenue", "Revenue Analytics"], ["trials", "Trials"], ["replacements", "Project Replacements"], ["ai", "AI Usage & Costs"],
  ["integrations", "Integrations & Webhooks"], ["health", "System Health"], ["audit", "Audit Logs"], ["settings", "Settings"],
] as const;

type TabKey = (typeof TABS)[number][0];

function AdminDashboard() {
  const router = useRouter();
  const params = useSearchParams();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [range, setRange] = useState<RangeValue>({ range: "30d", start: "", end: "" });
  const [mailNote, setMailNote] = useState<string | null>(null);
  const requested = params.get("tab");
  const tab: TabKey = (TABS.find(([k]) => k === requested)?.[0] ?? "overview") as TabKey;

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    getMe(token)
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.push("/login");
        else setLoadError("Could not check your account. Try again.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function sendLink() {
    try {
      const r = await sendVerificationEmail(getToken() ?? "");
      setMailNote(r.message);
    } catch (e) {
      setMailNote(e instanceof ApiError ? e.message : "Could not send the email.");
    }
  }

  function select(key: TabKey) {
    router.replace(`/dashboard/admin?tab=${key}`);
  }

  if (loading) return <main className={styles.page}><p className={styles.muted} role="status">Loading…</p></main>;
  if (loadError) return <main className={styles.page}><p className={styles.error} role="alert">{loadError}</p></main>;

  // The server enforces access on every admin request; this only avoids showing a page that cannot work.
  if (!me?.user.is_super_admin) {
    const needsVerify = me && !me.user.email_verified && me.user.email.toLowerCase() === "qaqadeer@gmail.com";
    return (
      <main className={styles.page}>
        <div className={styles.container}>
          <h1>Super Admin</h1>
          {needsVerify ? (
            <div className={styles.note}>
              <p>Verify your email address to unlock the Super Admin dashboard.</p>
              <button type="button" className={styles.primary} onClick={sendLink}>Send verification email</button>
              {mailNote && <p role="status">{mailNote}</p>}
            </div>
          ) : (
            <p className={styles.error} role="alert" data-testid="not-authorised">You do not have access to this area.</p>
          )}
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <header>
          <h1>Super Admin</h1>
          <p className={styles.subtitle}>Real records from the RankPilot database. Every change needs a reason and is written to the audit log.</p>
        </header>
        <nav className={styles.tabs} aria-label="Admin sections">
          {TABS.map(([key, label]) => (
            <button key={key} type="button" className={`${styles.tab} ${tab === key ? styles.tabActive : ""}`} aria-current={tab === key ? "page" : undefined} onClick={() => select(key)}>
              {label}
            </button>
          ))}
        </nav>
        {tab === "overview" && <OverviewSection range={range} setRange={setRange} />}
        {tab === "users" && <UsersSection />}
        {tab === "projects" && <ProjectsSection />}
        {tab === "subscriptions" && <SubscriptionsSection />}
        {tab === "payments" && <PaymentsSection range={range} setRange={setRange} />}
        {tab === "revenue" && <RevenueSection range={range} setRange={setRange} />}
        {tab === "trials" && <TrialsSection range={range} setRange={setRange} />}
        {tab === "replacements" && <ReplacementsSection range={range} setRange={setRange} />}
        {tab === "ai" && <AiCostsSection range={range} setRange={setRange} />}
        {tab === "integrations" && <WebhooksSection />}
        {tab === "health" && <HealthSection />}
        {tab === "audit" && <AuditSection />}
        {tab === "settings" && <SettingsSection />}
      </div>
    </main>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<main className={styles.page}><p role="status">Loading…</p></main>}>
      <AdminDashboard />
    </Suspense>
  );
}
