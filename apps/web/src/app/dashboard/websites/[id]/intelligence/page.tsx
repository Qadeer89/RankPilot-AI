"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ApiError, IntelKind, IntelResponse, MeResponse, getIntel, getMe, runIntel } from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "../growth/growth.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const TABS: { kind: IntelKind; label: string; blurb: string; button: string }[] = [
  { kind: "content", label: "Content", blurb: "How deep, well structured and trustworthy your pages look, from your latest crawl.", button: "Analyse content" },
  { kind: "technical", label: "Technical", blurb: "Live checks of your homepage, redirects, social tags, security headers and structured data.", button: "Run technical checks" },
  { kind: "lab", label: "Speed (lab)", blurb: "One measured page load in RankPilot's own mobile browser. Not real-visitor data.", button: "Measure homepage" },
  { kind: "competitors", label: "Competitors", blurb: "How your pages compare with competitor pages RankPilot has already crawled.", button: "Compare" },
  { kind: "keywords", label: "Keyword map", blurb: "Your real Search Console queries grouped into topics and mapped to pages.", button: "Build keyword map" },
];
const STATUS_CLASS: Record<string, string> = { pass: styles.good, warn: styles.neutral, fail: styles.bad, not_tested: styles.neutral };
const STATUS_LABEL: Record<string, string> = { pass: "Pass", warn: "Needs attention", fail: "Fail", not_tested: "Not tested" };
const when = (s?: string) => (s ? new Date(s).toLocaleString() : "");

/* eslint-disable @typescript-eslint/no-explicit-any */
function Body({ kind, run }: { kind: IntelKind; run: any }) {
  if (run.available === false) return <p className={styles.empty} data-testid="intel-unavailable">{run.reason ?? run.measurement?.reason ?? "Not available."}</p>;
  if (kind === "content") return (
    <>
      <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Part</th><th>Score</th><th>Weight</th><th>How</th></tr></thead><tbody>
        {run.parts.map((p: any) => <tr key={p.key}><td>{p.label}</td><td>{p.value === null ? <span className={`${styles.badge} ${styles.neutral}`}>Not available</span> : p.value}</td><td>{Math.round(p.weight * 100)}%</td><td className={styles.small}>{p.how} {p.note}</td></tr>)}
      </tbody></table></div>
      <p className={styles.small}>{run.findings.near_duplicate_body_text}</p>
      {run.findings.question_headings.length > 0 && <><h3>Question headings (snippet candidates)</h3><ul className={styles.list}>{run.findings.question_headings.slice(0, 8).map((q: any) => <li key={q.url + q.heading}>{q.heading}<span className={styles.small}>{q.url}</span></li>)}</ul><p className={styles.small}>{run.findings.question_heading_note}</p></>}
      {run.findings.near_duplicate_titles.length > 0 && <p className={styles.warn}>Near-duplicate titles: {run.findings.near_duplicate_titles.map((d: any) => `${d.a} ↔ ${d.b}`).join("; ")}</p>}
    </>
  );
  if (kind === "technical") return (
    <div className={styles.tableWrap}><table className={styles.table} data-testid="tech-checks"><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>
      {run.checks.map((c: any) => <tr key={c.key}><td>{c.label}{c.group === "security_hygiene" && <div className={styles.small}>hygiene, not a ranking factor</div>}</td><td><span className={`${styles.badge} ${STATUS_CLASS[c.status]}`}>{STATUS_LABEL[c.status]}</span></td><td className={styles.small}>{c.detail}</td></tr>)}
    </tbody></table></div>
  );
  if (kind === "lab") return (
    <>
      <div className={styles.stats}>
        {[["Time to first byte", run.measurement.ttfb_ms], ["DOM content loaded", run.measurement.dom_content_loaded_ms], ["Load", run.measurement.load_ms], ["Largest contentful paint", run.measurement.lcp_ms]].map(([l, v]) => (
          <div key={String(l)} className={styles.stat}><div className={styles.statLabel}>{l}</div><div className={styles.statValue}>{v == null ? "Not available" : `${v} ms`}</div></div>))}
        <div className={styles.stat}><div className={styles.statLabel}>Requests</div><div className={styles.statValue}>{run.measurement.requests}</div></div>
      </div>
      <p className={styles.small}>Lighthouse: {run.lighthouse.status === "tested" ? JSON.stringify(run.lighthouse.scores) : `Not tested. ${run.lighthouse.reason ?? ""}`}</p>
      {run.notes.map((n: string) => <p key={n} className={styles.small}>{n}</p>)}
    </>
  );
  if (kind === "competitors") return (
    <>
      <p className={styles.small}>Your site: {run.yours.pages} pages · median {run.yours.median_words ?? "—"} words · {Math.round((run.yours.structured_data_share ?? 0) * 100)}% with structured data</p>
      {run.competitors.map((c: any) => <article key={c.domain} className={styles.rec}><h3>{c.domain}</h3>
        {c.status === "analyzed" ? <><span>{c.pages} pages · median {c.median_words} words · {Math.round(c.structured_data_share * 100)}% with structured data · {c.avg_h2_per_page} H2s per page</span>
          <span className={styles.small}>Topic terms they use that your titles/headings do not: {c.topic_terms_missing_from_your_site.join(", ") || "none found"}</span></> : <span className={styles.small}>Not available — no pages analysed yet.</span>}</article>)}
      <p className={styles.small}>Not available without paid data: {run.not_available.join(", ")}.</p>
    </>
  );
  return (
    <>
      <p className={styles.small}>{run.note}</p>
      {run.clusters.slice(0, 30).map((c: any) => (
        <article key={c.label} className={styles.rec} data-testid="cluster"><h3>{c.label}</h3>
          <div className={styles.row}><span className={styles.badge}>{c.intent}</span><span className={styles.small}>{c.impressions} impressions · {c.clicks} clicks · {c.queries.length} queries</span>
            {c.possible_cannibalization && <span className={`${styles.badge} ${styles.bad}`}>Possible cannibalization</span>}</div>
          <span className={styles.small}>{c.pages.map((p: any) => `${p.url ?? "unknown page"} (${Math.round(p.share * 100)}%)`).join(" · ")}</span>
        </article>))}
    </>
  );
}

export default function IntelligencePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;
  const [tab, setTab] = useState<IntelKind>("content");
  const [loaded, setLoaded] = useState<{ kind: IntelKind; resp: IntelResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);

  const load = useCallback(() => {
    if (!token || !orgId) return;
    getIntel(token, orgId, websiteId, tab).then((resp) => setLoaded({ kind: tab, resp })).catch((e) => setError(msg(e)));
  }, [token, orgId, websiteId, tab]);
  useEffect(load, [load]);

  async function run() {
    if (!token || !orgId) return;
    setBusy(true); setError(null);
    try { await runIntel(token, orgId, websiteId, tab); load(); } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  }
  const meta = TABS.find((t) => t.kind === tab)!;
  const data = loaded && loaded.kind === tab ? loaded.resp : null;
  const loading = data === null && !error;
  const latest = data?.latest;
  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <Link href={`/dashboard/websites/${websiteId}`} className={styles.back}>← Back to project</Link>
          <h1>SEO Intelligence</h1>
          <p className={styles.sub}>Free-first analysis from your own site and Google data. Every result says where it came from and what could not be tested.</p>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <div className={styles.row} role="tablist">
          {TABS.map((t) => <button key={t.kind} role="tab" aria-selected={tab === t.kind} className={styles.btn} style={tab === t.kind ? { fontWeight: 700, borderColor: "var(--rp-primary)" } : undefined} onClick={() => setTab(t.kind)}>{t.label}</button>)}
        </div>
        <section className={styles.card} aria-label={meta.label}>
          <h2>{meta.label} {latest?.data_source && <span className={`${styles.badge} ${styles.neutral}`}>{latest.data_source}</span>}</h2>
          <p className={styles.small}>{meta.blurb}</p>
          {latest && (
            <div className={styles.row}>
              {latest.score != null && <span className={styles.badge} data-testid="intel-score">Score {latest.score}</span>}
              {latest.coverage != null && <span className={styles.small}>Data coverage {Math.round(latest.coverage * 100)}%</span>}
              <span className={styles.small}>Last updated {when(latest.computed_at)} · formula {latest.formula_version}</span>
            </div>
          )}
          {loading && <p className={styles.small} role="status">Loading…</p>}
          {!loading && !latest && <p className={styles.empty} data-testid="intel-empty">{data?.empty_reason}</p>}
          {latest && <Body kind={tab} run={latest} />}
          <div className={styles.row}><button className={styles.btn} onClick={run} disabled={busy}>{busy ? "Running…" : meta.button}</button></div>
        </section>
      </div>
    </main>
  );
}
