"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError, AuthorityResponse, BacklinkList, MeResponse, checkBacklinks, deleteBacklink, getAuthority, getMe, importBacklinks, listBacklinks, refreshAuthority,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "../growth/growth.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const STATUS: Record<string, [string, string]> = {
  live: ["Live", styles.good], link_removed: ["Link removed", styles.bad], unreachable: ["Page unreachable", styles.bad], blocked_by_robots: ["Blocked by robots.txt", styles.neutral],
  error: ["Check failed", styles.bad], unchecked: ["Not checked", styles.neutral],
};
const when = (s: string | null) => (s ? new Date(s).toLocaleString() : "Never");

export default function AuthorityPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;
  const [auth, setAuth] = useState<AuthorityResponse | null>(null);
  const [links, setLinks] = useState<BacklinkList | null>(null);
  const [text, setText] = useState("");
  const [source, setSource] = useState<"user_provided" | "gsc_export">("user_provided");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);

  const load = useCallback(() => {
    if (!token || !orgId) return;
    Promise.all([getAuthority(token, orgId, websiteId), listBacklinks(token, orgId, websiteId)])
      .then(([a, l]) => { setAuth(a); setLinks(l); })
      .catch((e) => setError(msg(e)))
      .finally(() => setLoaded(true));
  }, [token, orgId, websiteId]);
  useEffect(load, [load]);

  async function run(label: string, fn: () => Promise<string>) {
    setBusy(label); setError(null); setNotice(null);
    try { setNotice(await fn()); load(); } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  }
  const refresh = () => run("refresh", async () => { await refreshAuthority(token!, orgId!, websiteId); return "Domain quality recalculated from your latest crawl."; });
  const add = () => run("import", async () => {
    const r = await importBacklinks(token!, orgId!, websiteId, { text, source });
    setText("");
    return `Added ${r.added}. ${r.duplicates} already recorded.${r.rejected.length ? ` Rejected ${r.rejected.length}: ${r.rejected.slice(0, 3).map((x) => x.reason).join(" ")}` : ""}`;
  });
  const check = () => run("check", async () => {
    const r = await checkBacklinks(token!, orgId!, websiteId);
    return `Checked ${r.checked} source page${r.checked === 1 ? "" : "s"}.${r.checked === 0 ? " Nothing to check." : " Run again to check more."}`;
  });
  const remove = (id: string) => run("delete", async () => { await deleteBacklink(token!, orgId!, websiteId, id); return "Removed."; });

  const latest = auth?.latest;
  const an = links?.analysis;
  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <Link href={`/dashboard/websites/${websiteId}`} className={styles.back}>← Back to project</Link>
          <h1>Authority &amp; Backlinks</h1>
          <p className={styles.sub}>What RankPilot can verify about your site&apos;s strength, using only your own crawl, your Search Console data and pages you tell it about.</p>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {notice && <div className={styles.note} role="status">{notice}</div>}
        {!loaded && !error && <p className={styles.small} role="status">Loading…</p>}

        {loaded && auth && (
          <section className={styles.card} aria-label="Domain quality">
            <h2>Domain Quality {latest && <span className={`${styles.badge} ${styles.neutral}`}>{latest.data_source}</span>}</h2>
            <p className={styles.warn} data-testid="authority-disclaimer">{auth.disclaimer}</p>
            {!latest && <p className={styles.empty} data-testid="authority-empty">{auth.empty_reason}</p>}
            {latest && (
              <>
                <div className={styles.stats}>
                  <div className={styles.stat}><div className={styles.statLabel}>Domain quality</div><div className={styles.statValue} data-testid="dq-score">{latest.domain_quality ?? "Not available"}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Data coverage</div><div className={styles.statValue}>{Math.round(latest.coverage * 100)}%</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Confidence</div><div className={styles.statValue} style={{ textTransform: "capitalize" }}>{latest.confidence}</div></div>
                  <div className={styles.stat}><div className={styles.statLabel}>Last updated</div><div className={styles.statValue} style={{ fontSize: 14 }}>{when(latest.computed_at)}</div></div>
                </div>
                {auth.comparison?.available && auth.comparison.domain_quality_change != null && (
                  <p className={styles.small} data-testid="dq-change">Change since the previous assessment: {auth.comparison.domain_quality_change > 0 ? "+" : ""}{auth.comparison.domain_quality_change}. {auth.comparison.note}</p>
                )}
                {auth.comparison && !auth.comparison.available && <p className={styles.small}>{auth.comparison.reason}</p>}
                <div className={styles.tableWrap}>
                  <table className={styles.table} data-testid="signals">
                    <thead><tr><th>Signal</th><th>Score</th><th>Weight</th><th>How it is calculated</th></tr></thead>
                    <tbody>
                      {latest.signals.map((s) => (
                        <tr key={s.key}>
                          <td>{s.label}</td>
                          <td>{s.value === null ? <span className={`${styles.badge} ${styles.neutral}`}>Not available</span> : s.value}</td>
                          <td>{Math.round(s.weight * 100)}%</td>
                          <td><span className={styles.small}>{s.how}{s.note ? ` ${s.note}` : ""}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className={styles.small}>Formula {latest.formula_version}. Signals without data are left out and the rest are re-weighted; they are never counted as zero.</p>
              </>
            )}
            <div className={styles.row}><button className={styles.btn} onClick={refresh} disabled={busy !== null}>{busy === "refresh" ? "Calculating…" : "Recalculate now"}</button></div>
          </section>
        )}

        {loaded && links && an && (
          <section className={styles.card} aria-label="Backlinks">
            <h2>Backlinks you track</h2>
            <p className={styles.note} data-testid="backlink-label">{an.label}</p>
            <div className={styles.stats}>
              <div className={styles.stat}><div className={styles.statLabel}>Recorded</div><div className={styles.statValue}>{an.recorded}</div></div>
              <div className={styles.stat}><div className={styles.statLabel}>Verified live</div><div className={styles.statValue} data-testid="live-count">{an.verified_live}</div></div>
              <div className={styles.stat}><div className={styles.statLabel}>Referring domains (verified)</div><div className={styles.statValue}>{an.referring_domains}</div></div>
              <div className={styles.stat}><div className={styles.statLabel}>Not checked yet</div><div className={styles.statValue}>{an.unchecked}</div></div>
            </div>
            <div className={styles.form}>
              <label>Pages that link to your site (paste URLs or a Search Console links export)
                <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="https://example-blog.com/post-that-links-to-you" />
              </label>
              <div className={styles.row}>
                <label className={styles.small}>Where did these come from?{" "}
                  <select value={source} onChange={(e) => setSource(e.target.value as "user_provided" | "gsc_export")}>
                    <option value="user_provided">I found them myself</option><option value="gsc_export">Search Console export</option>
                  </select>
                </label>
                <button className={styles.btn} onClick={add} disabled={busy !== null || !text.trim()}>{busy === "import" ? "Adding…" : "Add pages"}</button>
                <button className={styles.btn} onClick={check} disabled={busy !== null || an.recorded === 0}>{busy === "check" ? "Checking…" : `Verify links (up to ${links.limits.max_checks_per_call})`}</button>
              </div>
            </div>
            {links.items.length === 0 ? <p className={styles.empty} data-testid="backlinks-empty">{links.empty_reason}</p> : (
              <div className={styles.tableWrap}>
                <table className={styles.table} data-testid="backlinks">
                  <thead><tr><th>Source page</th><th>Status</th><th>Anchor</th><th>Points to</th><th>Type</th><th>Checked</th><th /></tr></thead>
                  <tbody>
                    {links.items.map((b) => {
                      const [label, cls] = STATUS[b.status] ?? [b.status, styles.neutral];
                      return (
                        <tr key={b.id} data-testid="backlink-row">
                          <td style={{ wordBreak: "break-all" }}>{b.source_url}<div className={styles.small}>{b.data_source}</div></td>
                          <td><span className={`${styles.badge} ${cls}`}>{label}</span>{b.note && <div className={styles.small}>{b.note}</div>}</td>
                          <td>{b.anchor_text ?? "—"}</td>
                          <td style={{ wordBreak: "break-all" }}>{b.target_url ?? "—"}</td>
                          <td>{b.status === "live" ? (b.is_nofollow ? "nofollow / ugc / sponsored" : "followed") : "—"}{b.link_location ? ` · ${b.link_location}` : ""}</td>
                          <td className={styles.small}>{when(b.last_checked_at)}</td>
                          <td><button className={styles.btn} onClick={() => remove(b.id)} disabled={busy !== null} aria-label={`Remove ${b.source_url}`}>Remove</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {an.verified_live > 0 && (
              <div data-testid="anchor-mix">
                <h3>Anchor text of verified links</h3>
                <ul className={styles.list}>{an.anchor_distribution.map((a) => <li key={a.anchor}>{a.anchor} — {a.links} ({Math.round(a.share * 100)}%)</li>)}</ul>
              </div>
            )}
            {an.lost.length > 0 && <p className={styles.warn}>Links no longer found: {an.lost.map((l) => l.source_url).join(", ")}</p>}
          </section>
        )}
      </div>
    </main>
  );
}
