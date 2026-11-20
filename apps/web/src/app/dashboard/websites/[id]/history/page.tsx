"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError, HistoryCompare, HistoryDelta, HistoryEvent, HistoryOverview, HistorySearchComparison, HistorySeries, HistorySnapshotMeta, MeResponse,
  getHistoryCompare, getHistoryOverview, getHistorySearchComparison, getHistorySeries, getHistoryTimeline, getMe, listHistorySnapshots,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "./history.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

function fmt(value: number | null | undefined, label?: string): string {
  if (value === null || value === undefined) return "Not available";
  if (label === "CTR") return `${(value * 100).toFixed(2)}%`;
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(label === "Average position" ? 1 : 2);
}

function changeText(d: HistoryDelta): string {
  if (d.status === "not_available") return "Not available";
  if (d.status === "not_comparable") return "Not comparable";
  if (d.change === null) return "—";
  const sign = d.change > 0 ? "+" : "";
  const pct = d.change_pct === null ? "" : ` (${d.change_pct > 0 ? "+" : ""}${d.change_pct}%)`;
  if (d.label === "CTR") return `${sign}${(d.change * 100).toFixed(2)} percentage points${pct}`;  // CTR is stored as a fraction
  if (d.label === "Average position") return `${sign}${d.change.toFixed(1)}${pct}${d.change > 0 ? " (lower in results)" : d.change < 0 ? " (higher in results)" : ""}`;
  return `${sign}${d.change}${pct}`;
}

const STATUS_TEXT: Record<string, string> = { improved: "Improved", declined: "Declined", unchanged: "Unchanged", changed: "Changed", not_available: "Not available", not_comparable: "Not comparable", low_volume: "Too few to judge" };

function Status({ s }: { s: HistoryDelta["status"] }) {
  const cls = s === "improved" ? styles.good : s === "declined" ? styles.bad : styles.neutral;
  return <span className={`${styles.badge} ${cls}`}>{STATUS_TEXT[s]}</span>;
}

function DeltaTable({ rows, testId }: { rows: HistoryDelta[]; testId: string }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} data-testid={testId}>
        <thead><tr><th>Measure</th><th>Previous</th><th>Current</th><th>Change</th><th>Status</th><th>Source</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.group ?? ""}${r.label}`}>
              <td>{r.label}</td><td>{fmt(r.previous, r.label)}</td><td>{fmt(r.current, r.label)}</td><td>{changeText(r)}</td><td><Status s={r.status} /></td><td>{r.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Chart({ series }: { series: HistorySeries }) {
  const pts = series.points.filter((p) => p.value !== null) as { date: string; value: number }[];
  if (!series.available || pts.length === 0) {
    return <p className={styles.empty} data-testid="chart-empty">No data has been stored for this measure in this period.</p>;
  }
  const w = 720, h = 180, pad = 28;
  const min = Math.min(...pts.map((p) => p.value));
  const max = Math.max(...pts.map((p) => p.value));
  const span = max - min || 1;
  const x = (i: number) => pad + (pts.length === 1 ? (w - 2 * pad) / 2 : (i * (w - 2 * pad)) / (pts.length - 1));
  const y = (v: number) => h - pad - ((v - min) / span) * (h - 2 * pad);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={styles.chart} role="img" aria-label={`${series.label} over time`} data-testid="chart">
      <polyline className={styles.line} points={pts.map((p, i) => `${x(i)},${y(p.value)}`).join(" ")} />
      {pts.map((p, i) => <circle key={p.date + i} cx={x(i)} cy={y(p.value)} r={3} className={styles.dot}><title>{`${p.date}: ${p.value}`}</title></circle>)}
      <text x={pad} y={h - 6} className={styles.axis}>{pts[0].date}</text>
      <text x={w - pad} y={h - 6} textAnchor="end" className={styles.axis}>{pts[pts.length - 1].date}</text>
      <text x={4} y={pad} className={styles.axis}>{max}</text>
      <text x={4} y={h - pad} className={styles.axis}>{min}</text>
    </svg>
  );
}

const METRICS: [string, string][] = [
  ["health_overall", "SEO health score (RankPilot)"], ["issues_open", "Open issues (RankPilot)"], ["issues_critical", "Critical issues (RankPilot)"],
  ["clicks", "Clicks (Google Search Console)"], ["impressions", "Impressions (Google Search Console)"], ["ctr", "CTR (Google Search Console)"],
  ["position", "Average position (Google Search Console)"], ["sessions", "Sessions (Google Analytics)"], ["conversions", "Conversions (Google Analytics)"],
];
const CATEGORIES = ["", "project", "crawl", "snapshot", "integration", "issue", "recommendation", "implementation", "performance"];

export default function HistoryPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;

  const [overview, setOverview] = useState<HistoryOverview | null>(null);
  const [snapshots, setSnapshots] = useState<HistorySnapshotMeta[]>([]);
  const [from, setFrom] = useState("baseline");
  const [to, setTo] = useState("latest");
  const [compare, setCompare] = useState<HistoryCompare | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [period, setPeriod] = useState("28d");
  const [against, setAgainst] = useState("previous");
  const [cStart, setCStart] = useState("");
  const [cEnd, setCEnd] = useState("");
  const [search, setSearch] = useState<HistorySearchComparison | null>(null);
  const [metric, setMetric] = useState("health_overall");
  const [days, setDays] = useState(90);
  const [series, setSeries] = useState<HistorySeries | null>(null);
  const [category, setCategory] = useState("");
  const [tlPage, setTlPage] = useState(1);
  const [events, setEvents] = useState<{ items: HistoryEvent[]; pages: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    Promise.all([getHistoryOverview(token, orgId, websiteId), listHistorySnapshots(token, orgId, websiteId)])
      .then(([o, s]) => { if (!cancelled) { setOverview(o); setSnapshots(s.items); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(msg(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [token, orgId, websiteId]);

  useEffect(() => {
    if (!token || !orgId || !overview?.baseline) return;
    let cancelled = false;
    getHistoryCompare(token, orgId, websiteId, from, to)
      .then((c) => { if (!cancelled) { setCompare(c); setCompareError(null); } })
      .catch((e) => { if (!cancelled) { setCompare(null); setCompareError(msg(e)); } });
    return () => { cancelled = true; };
  }, [token, orgId, websiteId, from, to, overview?.baseline]);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    getHistorySearchComparison(token, orgId, websiteId, period, against, cStart, cEnd)
      .then((r) => !cancelled && setSearch(r))
      .catch((e) => !cancelled && setSearch({ available: false, reason: msg(e), rows: [], freshness: { latest_data_date: null, last_synced_at: null, note: "" } }));
    return () => { cancelled = true; };
  }, [token, orgId, websiteId, period, against, cStart, cEnd]);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    getHistorySeries(token, orgId, websiteId, metric, days)
      .then((s) => !cancelled && setSeries(s))
      .catch((e) => !cancelled && setError(msg(e)));
    return () => { cancelled = true; };
  }, [token, orgId, websiteId, metric, days]);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    getHistoryTimeline(token, orgId, websiteId, category, tlPage)
      .then((t) => !cancelled && setEvents(t))
      .catch((e) => !cancelled && setError(msg(e)));
    return () => { cancelled = true; };
  }, [token, orgId, websiteId, category, tlPage]);

  const snapLabel = (s: HistorySnapshotMeta) => {
    const when = new Date(s.taken_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
    const score = s.health_overall !== null && s.health_overall !== undefined ? ` · score ${Math.round(s.health_overall * 10) / 10}` : "";
    return `${when}${score}${s.is_baseline ? " · baseline" : ""}${s.reconstructed ? " · rebuilt" : ""}`;
  };

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <Link href={`/dashboard/websites/${websiteId}`} className={styles.back}>← Back to project</Link>
        <Link href={`/dashboard/websites/${websiteId}/report`} className={styles.back}>Customer progress report</Link>
        <header className={styles.header}>
          <h1>SEO Performance · History &amp; Progress</h1>
          <p className={styles.sub}>Where this project started, what has changed since, and what still needs attention. Every figure shows its source.</p>
        </header>
        {error && <p className={styles.error} role="alert" data-testid="history-error">{error}</p>}
        {loading && !error && <p className={styles.small} role="status">Loading…</p>}

        {overview && (
          <section className={styles.card} aria-label="Overall progress">
            <h2>Overall progress</h2>
            {!overview.baseline ? (
              <p className={styles.empty} data-testid="no-baseline">No analysis has completed for this project yet, so there is no baseline. It is saved automatically when the first crawl finishes.</p>
            ) : (
              <>
                <div className={styles.stats}>
                  <div className={styles.stat}><div className={styles.statLabel}>Initial health score</div><div className={styles.statValue}>{fmt(overview.health.initial)}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Current health score</div><div className={styles.statValue}>{fmt(overview.health.current)}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Change since baseline</div><div className={styles.statValue}>{changeText(overview.health)}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Issues identified</div><div className={styles.statValue}>{overview.issues.identified_total}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Issues resolved</div><div className={styles.statValue}>{overview.issues.resolved}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Still open</div><div className={styles.statValue}>{overview.issues.still_open}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>New since baseline</div><div className={styles.statValue}>{overview.issues.new_since_baseline ?? "Not available"}</div></div>
                  <p className={styles.small} data-testid="issues-note" style={{ gridColumn: "1 / -1" }}>{overview.issues.note}</p>
                  {overview.health.like_for_like && (
                    <div className={styles.stat} data-testid="like-for-like"><div className={styles.statLabel}>Same components ({overview.health.like_for_like.components.join(", ").replace(/_/g, "-")})</div>
                      <div className={styles.statValue}>{overview.health.like_for_like.previous} → {overview.health.like_for_like.current}</div></div>
                  )}
                  {overview.work.changes_applied !== undefined && (
                    <div className={styles.stat}><div className={styles.statLabel}>Changes applied</div><div className={styles.statValue}>{overview.work.changes_applied}</div></div>
                  )}
                  <div className={styles.stat}><div className={styles.statLabel}>Pages optimized</div><div className={styles.statValue}>{overview.work.pages_optimized}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Recommendations implemented</div><div className={styles.statValue}>{overview.work.recommendations_implemented}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Recommendations validated</div><div className={styles.statValue}>{overview.work.recommendations_validated}</div></div>
                </div>
                <p className={styles.note}>{overview.health.note}</p>
                {overview.baseline.reconstructed && <p className={styles.warn}>The baseline was rebuilt from the health score stored at the time; the list of individual issues at that date is not available.</p>}
              </>
            )}
            <ul className={styles.small} data-testid="data-sources">
              {Object.entries(overview.data_sources).map(([name, s]) => (
                <li key={name}>{name === "crawler" ? "RankPilot crawl" : name === "google_search_console" ? "Google Search Console" : "Google Analytics"}: {s.available ? "data stored" : s.reason}</li>
              ))}
            </ul>
          </section>
        )}

        {overview?.baseline && (
          <section className={styles.card} aria-label="Before and after">
            <h2>Before and after</h2>
            <div className={styles.controls}>
              <label>Earlier
                <select value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Earlier snapshot">
                  <option value="baseline">Project baseline</option>
                  {snapshots.map((s) => <option key={s.id} value={s.id}>{snapLabel(s)}</option>)}
                </select>
              </label>
              <label>Later
                <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Later snapshot">
                  <option value="latest">Latest</option>
                  <option value="previous">Previous snapshot</option>
                  {snapshots.map((s) => <option key={s.id} value={s.id}>{snapLabel(s)}</option>)}
                </select>
              </label>
            </div>
            {compareError && <p className={styles.warn} data-testid="compare-error">{compareError}</p>}
            {compare && (
              <>
                <p className={styles.small}>Comparing {compare.comparison_period.start} with {compare.comparison_period.end}.</p>
                {compare.warnings.map((w) => <p key={w} className={styles.warn}>{w}</p>)}
                <DeltaTable rows={compare.rows} testId="compare-table" />
                <p data-testid="issue-changes">
                  {compare.issue_changes.available
                    ? `Resolved ${compare.issue_changes.resolved} · New ${compare.issue_changes.new} · Still open ${compare.issue_changes.still_open}`
                    : compare.issue_changes.reason}
                </p>
              </>
            )}
          </section>
        )}

        <section className={styles.card} aria-label="Organic search performance">
          <h2>Organic search performance</h2>
          <div className={styles.controls}>
            <label>Period
              <select value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Period">
                <option value="7d">Last 7 days</option><option value="28d">Last 28 days</option><option value="3m">Last 3 months</option><option value="custom">Custom range</option>
              </select>
            </label>
            {period === "custom" && (
              <>
                <label>From<input type="date" value={cStart} onChange={(e) => setCStart(e.target.value)} /></label>
                <label>To<input type="date" value={cEnd} onChange={(e) => setCEnd(e.target.value)} /></label>
              </>
            )}
            <label>Compare with
              <select value={against} onChange={(e) => setAgainst(e.target.value)} aria-label="Compare with">
                <option value="previous">The previous period</option><option value="baseline">The project baseline</option>
              </select>
            </label>
          </div>
          {search && !search.available && search.rows.length === 0 && <p className={styles.empty} data-testid="search-unavailable">{search.reason}</p>}
          {search?.warnings?.map((w) => <p key={w} className={styles.warn} data-testid="search-warning">{w}</p>)}
          {search && search.rows.length > 0 && (
            <>
              {search.current && search.previous && (
                <p className={styles.small}>Current: {search.current.start} to {search.current.end} · Compared with: {search.previous.start} to {search.previous.end}</p>
              )}
              <DeltaTable rows={search.rows} testId="search-table" />
              <p className={styles.small}>Latest data date: {search.freshness.latest_data_date ?? "n/a"}. {search.freshness.note}</p>
              {search.note && <p className={styles.note}>{search.note}</p>}
            </>
          )}
        </section>

        <section className={styles.card} aria-label="Trends">
          <h2>Trends</h2>
          <div className={styles.controls}>
            <label>Measure
              <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Measure">
                {METRICS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>Range
              <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Range">
                <option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 6 months</option><option value={365}>Last 12 months</option>
              </select>
            </label>
          </div>
          {series && <><Chart series={series} /><p className={styles.small}>Source: {series.source}. {series.note}</p></>}
        </section>

        <section className={styles.card} aria-label="Activity timeline">
          <h2>Activity timeline</h2>
          <div className={styles.controls}>
            <label>Category
              <select value={category} onChange={(e) => { setCategory(e.target.value); setTlPage(1); }} aria-label="Category">
                {CATEGORIES.map((c) => <option key={c} value={c}>{c ? c[0].toUpperCase() + c.slice(1) : "All events"}</option>)}
              </select>
            </label>
          </div>
          {events && events.items.length === 0 ? <p className={styles.empty} data-testid="timeline-empty">No events yet.</p> : (
            <ul className={styles.timeline} data-testid="timeline">
              {events?.items.map((e) => (
                <li key={e.id}><span className={styles.when}>{new Date(e.occurred_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</span><span>{e.title}</span></li>
              ))}
            </ul>
          )}
          {events && events.pages > 1 && (
            <div className={styles.controls}>
              <button type="button" className={styles.btn} disabled={tlPage <= 1} onClick={() => setTlPage(tlPage - 1)}>Previous</button>
              <span className={styles.small}>Page {tlPage} of {events.pages}</span>
              <button type="button" className={styles.btn} disabled={tlPage >= events.pages} onClick={() => setTlPage(tlPage + 1)}>Next</button>
            </div>
          )}
        </section>

        <p className={styles.small}>RankPilot&apos;s health score measures the condition of your website. It is not a Google ranking. Search performance is influenced by competition, search engine updates, demand and many other factors, so a change in these numbers does not by itself show that any RankPilot action caused it.</p>
      </div>
    </main>
  );
}
