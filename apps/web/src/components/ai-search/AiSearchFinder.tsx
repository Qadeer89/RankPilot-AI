"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AiSearchDetail, AiSearchFilters, AiSearchFinding, AiSearchMonitoring, AiSearchOpportunity, AiSearchOpportunityList, AiSearchSummary, ApiError,
  analyzeAiSearchQuery, decideAiSearchFinding, editAiSearchDraft, getAiSearchDetail, getAiSearchMonitoring, getAiSearchSummary,
  listAiSearchOpportunities, markAiSearchImplemented,
} from "@/lib/api";
import styles from "./ai-search.module.css";

interface Props { token: string; organizationId: string; websiteId: string; country: string }

const RANGES: [string, string][] = [["7d", "Last 7 days"], ["28d", "Last 28 days"], ["3m", "Last 3 months"], ["6m", "Last 6 months"], ["custom", "Custom range"]];
const CATEGORIES: [string, string][] = [["", "All categories"], ["question", "Question-based"], ["long_tail", "Long-tail"], ["conversational", "Conversational"], ["comparison", "Comparison"], ["problem_solution", "Problem / solution"], ["very_long", "Very long (8+ words)"]];
const TIERS: [string, string][] = [["", "All opportunity types"], ["high_opportunity", "High opportunity"], ["content_gap", "Content gap"], ["ranking_improvement", "Ranking improvement"], ["low_priority", "Low priority"]];
const STATUSES: [string, string][] = [["", "Any status"], ["new", "New"], ["ready_for_review", "Ready for review"], ["approved", "Approved"], ["rejected", "Rejected"], ["implemented", "Implemented"], ["validation_failed", "Validation failed"], ["monitoring", "Monitoring"], ["completed", "Completed"]];
const TIER_LABEL: Record<string, string> = { high_opportunity: "High opportunity", content_gap: "Content gap", ranking_improvement: "Ranking improvement", low_priority: "Low priority" };
const STATUS_LABEL: Record<string, string> = Object.fromEntries(STATUSES.filter(([k]) => k).map(([k, v]) => [k, v]));
const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES.filter(([k]) => k).map(([k, v]) => [k, v]));

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`);
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

function tierClass(tier: string) {
  return tier === "high_opportunity" ? styles.badgeGood : tier === "content_gap" ? styles.badgeWarn : tier === "low_priority" ? "" : styles.badgeWarn;
}

export default function AiSearchFinder({ token, organizationId, websiteId, country }: Props) {
  const [filters, setFilters] = useState<AiSearchFilters>({ range: "28d", sort: "score", direction: "desc", page: 1, page_size: 25 });
  const [summary, setSummary] = useState<AiSearchSummary | null>(null);
  const [list, setList] = useState<AiSearchOpportunityList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openQuery, setOpenQuery] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const effective: AiSearchFilters = { ...filters, country: country || undefined };
  const key = JSON.stringify(effective) + tick;

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getAiSearchSummary(token, organizationId, websiteId, effective),
      listAiSearchOpportunities(token, organizationId, websiteId, effective),
    ])
      .then(([s, l]) => {
        if (cancelled) return;
        setSummary(s);
        setList(l);
        setError(null);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(message(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, organizationId, websiteId, key]);

  const set = (patch: Partial<AiSearchFilters>) => setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }));
  const reload = useCallback(() => setTick((t) => t + 1), []);

  return (
    <div className={styles.root} data-testid="ai-search">
      <p className={styles.note}>
        {summary?.explanation ??
          "These are Google Search queries from Search Console, not prompts typed into ChatGPT, Gemini or other AI tools. Nothing here guarantees a ranking or an AI citation."}
      </p>
      {error && (
        <p className={styles.error} role="alert" data-testid="ai-search-error">
          {error}{" "}
          <button type="button" className={styles.linkButton} onClick={reload}>Try again</button>
        </p>
      )}
      {summary?.warnings.map((w) => (
        <p key={w} className={styles.warn}>{w}</p>
      ))}

      <div className={styles.cards}>
        {summary && [
          ["Conversational queries", summary.totals.conversational_queries], ["Question-based queries", summary.totals.question_queries],
          ["Long-tail queries", summary.totals.long_tail_queries], ["High-opportunity queries", summary.totals.high_opportunity],
          ["Pages with improvement opportunities", summary.totals.pages_with_opportunities], ["Potential content gaps", summary.totals.potential_content_gaps],
        ].map(([label, value]) => (
          <div key={label as string} className={styles.stat}>
            <div className={styles.statLabel}>{label}</div>
            <div className={styles.statValue}>{value as number}</div>
          </div>
        ))}
      </div>

      <div className={styles.filters} role="search" aria-label="Opportunity filters">
        <label>Period
          <select value={filters.range} onChange={(e) => set({ range: e.target.value })}>
            {RANGES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {filters.range === "custom" && (
          <>
            <label>From<input type="date" value={filters.start ?? ""} onChange={(e) => set({ start: e.target.value })} /></label>
            <label>To<input type="date" value={filters.end ?? ""} onChange={(e) => set({ end: e.target.value })} /></label>
          </>
        )}
        <label>Device
          <select value={filters.device ?? ""} onChange={(e) => set({ device: e.target.value })}>
            <option value="">All devices</option><option value="MOBILE">Mobile</option><option value="DESKTOP">Desktop</option><option value="TABLET">Tablet</option>
          </select>
        </label>
        <label>Category
          <select value={filters.category ?? ""} onChange={(e) => set({ category: e.target.value })}>
            {CATEGORIES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Opportunity type
          <select value={filters.tier ?? ""} onChange={(e) => set({ tier: e.target.value })}>
            {TIERS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Status
          <select value={filters.recommendation_status ?? ""} onChange={(e) => set({ recommendation_status: e.target.value })}>
            {STATUSES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Min impressions<input type="number" min={0} value={filters.min_impressions ?? ""} onChange={(e) => set({ min_impressions: e.target.value })} /></label>
        <label>Max position<input type="number" min={0} value={filters.max_position ?? ""} onChange={(e) => set({ max_position: e.target.value })} /></label>
        <label>Min score<input type="number" min={0} max={100} value={filters.min_score ?? ""} onChange={(e) => set({ min_score: e.target.value })} /></label>
        <label>Search query<input type="search" value={filters.q ?? ""} onChange={(e) => set({ q: e.target.value })} placeholder="contains…" /></label>
        <label>Sort
          <select value={filters.sort} onChange={(e) => set({ sort: e.target.value })}>
            <option value="score">Opportunity score</option><option value="impressions">Impressions</option><option value="clicks">Clicks</option>
            <option value="ctr">CTR</option><option value="position">Average position</option><option value="query">Query</option>
          </select>
        </label>
      </div>

      {loading ? (
        <p className={styles.small} role="status">Loading…</p>
      ) : list && list.items.length === 0 ? (
        <p className={styles.empty} data-testid="ai-search-empty">
          {summary && summary.data_coverage.rows === 0
            ? "No Search Console data is stored for this project yet. Connect Search Console and sync first."
            : "No conversational, question-based or long-tail queries match these filters."}
        </p>
      ) : (
        list && (
          <>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Search query</th><th>Category</th><th>Landing page</th><th>Country</th><th>Impressions</th><th>Clicks</th><th>CTR</th>
                    <th>Avg. position</th><th>Score</th><th>Recommendation</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((o) => (
                    <tr key={o.query}>
                      <td className={styles.queryCell}>
                        <button type="button" className={styles.linkButton} onClick={() => setOpenQuery(o.query)}>{o.query}</button>
                      </td>
                      <td>{o.categories.slice(0, 3).map((c) => <span key={c} className={styles.badge}>{CATEGORY_LABEL[c] ?? c}</span>)}</td>
                      <td>{o.landing_page ? <span title={o.landing_page.url}>{new URL(o.landing_page.url).pathname}</span> : <span className={styles.small}>none known</span>}
                        {o.needs_review && <span className={`${styles.badge} ${styles.badgeWarn}`}>pages compete</span>}</td>
                      <td>{o.country ?? "n/a"}</td>
                      <td>{o.impressions}</td><td>{o.clicks}</td><td>{pct(o.ctr)}</td><td>{o.average_position.toFixed(1)}</td>
                      <td title={o.factors.filter((f) => f.max).map((f) => `${f.factor}: ${f.points}/${f.max}`).join("\n")}>{o.score}</td>
                      <td><span className={`${styles.badge} ${tierClass(o.tier)}`}>{TIER_LABEL[o.tier]}</span></td>
                      <td>{STATUS_LABEL[o.status] ?? o.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.pager}>
              <span className={styles.small}>{list.total} quer{list.total === 1 ? "y" : "ies"}</span>
              <button type="button" className={styles.btn} disabled={list.page <= 1} onClick={() => set({ page: list.page - 1 })}>Previous</button>
              <span aria-live="polite">Page {list.page} of {list.pages}</span>
              <button type="button" className={styles.btn} disabled={list.page >= list.pages} onClick={() => set({ page: list.page + 1 })}>Next</button>
            </div>
          </>
        )
      )}

      {openQuery && (
        <QueryDetail token={token} organizationId={organizationId} websiteId={websiteId} query={openQuery} filters={effective}
          onClose={() => { setOpenQuery(null); reload(); }} />
      )}
    </div>
  );
}

function Spark({ points }: { points: { date: string; impressions: number }[] }) {
  const max = Math.max(1, ...points.map((p) => p.impressions));
  const w = 560, h = 60, bw = w / Math.max(points.length, 1);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={styles.spark} role="img" aria-label="Daily impressions">
      {points.map((p, i) => <rect key={p.date} x={i * bw + 1} y={h - (p.impressions / max) * h} width={Math.max(bw - 2, 1)} height={(p.impressions / max) * h} className={styles.sparkBar}><title>{`${p.date}: ${p.impressions}`}</title></rect>)}
    </svg>
  );
}

function QueryDetail({ token, organizationId, websiteId, query, filters, onClose }: {
  token: string; organizationId: string; websiteId: string; query: string; filters: AiSearchFilters; onClose: () => void;
}) {
  const [detail, setDetail] = useState<AiSearchDetail | null>(null);
  const [finding, setFinding] = useState<AiSearchFinding | null>(null);
  const [monitoring, setMonitoring] = useState<AiSearchMonitoring | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [heading, setHeading] = useState("");
  const [note, setNote] = useState("");

  const adopt = useCallback((f: AiSearchFinding) => {
    setFinding(f);
    setAnswer(f.draft?.direct_answer ?? "");
    setHeading(f.draft?.suggested_heading ?? "");
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAiSearchDetail(token, organizationId, websiteId, query, filters)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        if (d.finding) adopt(d.finding);
      })
      .catch((e) => !cancelled && setError(message(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, organizationId, websiteId, query]);

  useEffect(() => {
    if (!finding?.id || !finding.implemented_at) return;
    let cancelled = false;
    getAiSearchMonitoring(token, organizationId, websiteId, finding.id)
      .then((m) => !cancelled && setMonitoring(m))
      .catch(() => !cancelled && setMonitoring(null));
    return () => {
      cancelled = true;
    };
  }, [token, organizationId, websiteId, finding?.id, finding?.implemented_at]);

  async function run(name: string, fn: () => Promise<AiSearchFinding>) {
    setBusy(name);
    setError(null);
    try {
      adopt(await fn());
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  const op: AiSearchOpportunity | undefined = detail?.opportunity;
  const stage = finding?.status ?? "new";
  const editable = !!finding?.draft && ["ready_for_review", "new"].includes(stage);

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={`Query details: ${query}`}>
      <div className={styles.drawer}>
        <div className={styles.actions} style={{ justifyContent: "space-between" }}>
          <h2>{query}</h2>
          <button type="button" className={styles.btn} onClick={onClose}>Close</button>
        </div>
        {error && <p className={styles.error} role="alert" data-testid="detail-error">{error}</p>}
        {!op ? <p className={styles.small} role="status">Loading…</p> : (
          <>
            <p>{op.categories.map((c) => <span key={c} className={styles.badge}>{CATEGORY_LABEL[c] ?? c}</span>)}
              <span className={`${styles.badge} ${tierClass(op.tier)}`}>{TIER_LABEL[op.tier]}</span></p>
            <dl className={styles.facts}>
              <dt>Landing page</dt><dd>{op.landing_page?.url ?? "No crawled page is known for this query"}</dd>
              <dt>Impressions / clicks</dt><dd>{op.impressions} / {op.clicks} (CTR {pct(op.ctr)})</dd>
              <dt>Average position</dt><dd>{op.average_position.toFixed(1)}</dd>
              <dt>Opportunity score</dt><dd>{op.score} / 100</dd>
              <dt>Status</dt><dd>{STATUS_LABEL[stage] ?? stage}</dd>
            </dl>
            <h3>Search Console history</h3>
            <Spark points={detail?.history ?? []} />
            <h3>Why this score</h3>
            <ul className={styles.checks}>
              {op.factors.filter((f) => f.max).map((f) => <li key={f.factor}><strong>{f.factor}</strong> {f.points}/{f.max}: {f.note}</li>)}
              {op.factors.filter((f) => !f.max).map((f) => <li key={f.note}>{f.note}</li>)}
            </ul>
            {op.other_pages.length > 0 && (
              <p className={styles.warn}>Other pages also receive this query: {op.other_pages.map((p) => p.url).join(", ")}. Decide which page should own it before changing anything.</p>
            )}

            {!finding && (
              <div className={styles.actions}>
                <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} disabled={busy !== null}
                  onClick={() => run("analyze", () => analyzeAiSearchQuery(token, organizationId, websiteId, { query, country: filters.country, range: filters.range, start: filters.start, end: filters.end }))}>
                  {busy === "analyze" ? "Analyzing…" : "Generate Content Improvement Recommendation"}
                </button>
              </div>
            )}

            {finding && (
              <>
                <h3>Does the page answer it?</h3>
                <p>{finding.answer_analysis.reason} <span className={styles.badge}>{finding.answer_analysis.level}</span></p>
                {finding.ai_error && <p className={styles.warn} data-testid="ai-note">{finding.ai_error}</p>}

                {finding.draft && (
                  <>
                    <h3>Suggested direct answer</h3>
                    <p className={styles.small}>{finding.label}</p>
                    {editable ? (
                      <div className={styles.editor}>
                        <label>Suggested heading<input value={heading} onChange={(e) => setHeading(e.target.value)} /></label>
                        <label>Direct answer<textarea value={answer} onChange={(e) => setAnswer(e.target.value)} /></label>
                        <div className={styles.actions}>
                          <button type="button" className={styles.btn} disabled={busy !== null}
                            onClick={() => run("edit", () => editAiSearchDraft(token, organizationId, websiteId, finding.id, { direct_answer: answer, suggested_heading: heading }))}>
                            Save edits and re-check
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className={styles.draft}><strong>{finding.draft.suggested_heading}</strong><p>{finding.draft.direct_answer}</p></div>
                    )}
                    {finding.draft.missing_information.length > 0 && (<><h3>Missing information</h3><ul>{finding.draft.missing_information.map((m) => <li key={m}>{m}</li>)}</ul></>)}
                    {finding.draft.needs_owner_input.length > 0 && (<><h3>Needs your input</h3><ul>{finding.draft.needs_owner_input.map((m) => <li key={m}>{m}</li>)}</ul></>)}
                    {finding.draft.faq_recommended && finding.draft.faq_suggestions.length > 0 && (
                      <><h3>Suggested FAQs</h3><ul>{finding.draft.faq_suggestions.map((f) => <li key={f.question}><strong>{f.question}</strong> {f.answer}</li>)}</ul></>
                    )}
                    {finding.draft.internal_links.length > 0 && (
                      <><h3>Suggested internal links</h3><ul>{finding.draft.internal_links.map((l) => <li key={l.target_url}>{l.anchor_text} → {l.target_url}</li>)}</ul></>
                    )}
                    <p className={styles.small}>Rationale: {finding.draft.rationale} (model confidence {Math.round((finding.confidence ?? 0) * 100)}%)</p>
                    {finding.quality && (
                      <>
                        <h3>Quality checks</h3>
                        <ul className={styles.checks} data-testid="quality-checks">
                          {finding.quality.checks.map((c) => (
                            <li key={c.check}><span className={`${styles.badge} ${c.status === "pass" ? styles.badgeGood : c.status === "fail" ? styles.badgeBad : styles.badgeWarn}`}>{c.status}</span> {c.check}: {c.detail}</li>
                          ))}
                        </ul>
                      </>
                    )}
                  </>
                )}

                <h3>AI search content readiness</h3>
                <p className={styles.small}>{finding.ai_search_readiness.disclaimer}</p>
                {finding.ai_search_readiness.checks?.length ? (
                  <>
                    <p><span className={styles.badge}>{finding.ai_search_readiness.label.replace("_", " ")}</span> {finding.ai_search_readiness.passed}/{finding.ai_search_readiness.total} checks passed. AI-platform visibility: <strong>{finding.ai_search_readiness.ai_visibility}</strong></p>
                    <ul className={styles.checks}>
                      {finding.ai_search_readiness.checks.map((c) => (
                        <li key={c.check}><span className={`${styles.badge} ${c.status === "pass" ? styles.badgeGood : c.status === "fail" ? styles.badgeBad : styles.badgeWarn}`}>{c.status}</span> {c.check} <span className={styles.small}>({c.evidence})</span>{c.advice ? ` — ${c.advice}` : ""}</li>
                      ))}
                    </ul>
                  </>
                ) : <p className={styles.small}>Not available: the page could not be read.</p>}

                {finding.recommendation && (
                  <>
                    <h3>Recommendation</h3>
                    <dl className={styles.facts}>
                      <dt>Priority</dt><dd>{finding.recommendation.priority}</dd>
                      <dt>Difficulty</dt><dd>{finding.recommendation.difficulty}</dd>
                      <dt>Expected benefit</dt><dd>{finding.recommendation.expected_benefit}</dd>
                      <dt>Approval</dt><dd>{finding.recommendation.requires_approval ? "Required before it counts as approved" : "Not required"}</dd>
                    </dl>
                    <p className={styles.note} data-testid="execution-note">{finding.execution.reason}</p>
                    <div className={styles.actions}>
                      {stage === "ready_for_review" && (
                        <>
                          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} disabled={busy !== null || finding.quality?.blocked}
                            onClick={() => run("approve", () => decideAiSearchFinding(token, organizationId, websiteId, finding.id, "approve"))}>Approve</button>
                          <button type="button" className={styles.btn} disabled={busy !== null}
                            onClick={() => run("reject", () => decideAiSearchFinding(token, organizationId, websiteId, finding.id, "reject"))}>Reject</button>
                        </>
                      )}
                      {stage === "rejected" && (
                        <button type="button" className={styles.btn} disabled={busy !== null}
                          onClick={() => run("analyze", () => analyzeAiSearchQuery(token, organizationId, websiteId, { query, country: filters.country, range: filters.range, start: filters.start, end: filters.end }))}>Regenerate</button>
                      )}
                    </div>
                    {stage === "approved" && (
                      <div className={styles.editor}>
                        <p>Approved. Add the text to your page in your CMS, then confirm here. RankPilot will re-read the public page.</p>
                        <label>Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                        <div className={styles.actions}>
                          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} disabled={busy !== null}
                            onClick={() => run("implemented", () => markAiSearchImplemented(token, organizationId, websiteId, finding.id, note))}>Mark as implemented</button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {finding.implemented_at && (
                  <>
                    <h3>Verification</h3>
                    <p data-testid="live-check">
                      {finding.live_check?.matched === true && "The public page now shows the change."}
                      {finding.live_check?.matched === false && "The public page does not show the change yet (caches and builds can lag)."}
                      {finding.live_check?.matched === null && `Could not verify yet: ${finding.live_check?.error ?? "no result"}`}
                    </p>
                    {finding.live_check?.matched !== true && (
                      <button type="button" className={styles.btn} disabled={busy !== null}
                        onClick={() => run("recheck", () => decideAiSearchFinding(token, organizationId, websiteId, finding.id, "recheck"))}>Check the page again</button>
                    )}
                    {monitoring && (
                      <div data-testid="monitoring">
                        <h3>Performance monitoring ({monitoring.window_days} days before and after)</h3>
                        <table className={styles.table}>
                          <thead><tr><th /><th>Clicks</th><th>Impressions</th><th>CTR</th><th>Avg. position</th></tr></thead>
                          <tbody>
                            {(["before", "after"] as const).map((k) => (
                              <tr key={k}><td>{k}</td><td>{monitoring[k]?.clicks ?? "no data"}</td><td>{monitoring[k]?.impressions ?? "no data"}</td><td>{pct(monitoring[k]?.ctr)}</td><td>{monitoring[k]?.average_position ?? "n/a"}</td></tr>
                            ))}
                          </tbody>
                        </table>
                        {!monitoring.after_window_complete && <p className={styles.warn}>The after period is not complete yet; Search Console reports with a delay.</p>}
                        <p className={styles.small}>{monitoring.note} {monitoring.caveat}</p>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
