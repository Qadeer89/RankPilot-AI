"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ApiError, MeResponse, ProgressReport, getMe, getProgressReport } from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "./report.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const day = (iso: string | undefined) => (iso ? new Date(iso).toLocaleDateString() : "—");

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;
  const [report, setReport] = useState<ProgressReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);
  useEffect(() => {
    if (!token || !orgId) return;
    getProgressReport(token, orgId, websiteId).then(setReport).catch((e) => setError(msg(e)));
  }, [token, orgId, websiteId]);

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={`${styles.noPrint} ${styles.row}`}>
          <Link href={`/dashboard/websites/${websiteId}/history`} className={styles.back}>← History &amp; Progress</Link>
          <button className={styles.btn} onClick={() => window.print()} disabled={!report}>Print or save as PDF</button>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {report && (
          <article className={styles.card} data-testid="report">
            <h1>SEO progress report</h1>
            <p className={styles.sub}>{report.project.name} · {report.project.url}</p>
            <p className={styles.small}>Generated {day(report.generated_at)}{report.period ? ` · Comparing ${report.period.start} to ${report.period.end}` : ""}</p>

            {!report.has_progress && <p className={styles.note} data-testid="no-progress">Your starting point is saved ({day(report.baseline?.taken_at)}). Progress appears here after the next analysis.</p>}

            <h2>Website health (RankPilot&apos;s own measure)</h2>
            <p>Start: {report.health.initial ?? "Not available"} · Now: {report.health.current ?? "Not available"}</p>
            <p className={styles.small}>{report.health.note}</p>

            <h2>What changed</h2>
            {report.highlights.length === 0 ? <p className={styles.small}>Nothing to compare yet.</p> : <ul>{report.highlights.map((h) => <li key={h}>{h}</li>)}</ul>}
            {report.warnings.map((w) => <p key={w} className={styles.warn}>{w}</p>)}

            <h2>Google search performance</h2>
            {report.google.available ? <ul data-testid="google-lines">{report.google.lines.map((l) => <li key={l}>{l}</li>)}</ul> : <p data-testid="google-na">Not available — {report.google.reason}</p>}

            <h2>Data used</h2>
            <ul>{Object.entries(report.data_sources).map(([k, v]) => <li key={k}>{k.replace(/_/g, " ")}: {v.available ? "available" : `Not available — ${v.reason}`}</li>)}</ul>

            <h2>Please note</h2>
            <ul data-testid="limitations">{report.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </article>
        )}
      </div>
    </main>
  );
}
