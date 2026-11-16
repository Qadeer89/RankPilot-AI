"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { adminGet, type Query } from "@/lib/adminApi";
import styles from "./admin.module.css";

export function useAdminData<T>(path: string, params: Query = {}) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const key = path + JSON.stringify(params);
  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let cancelled = false;
    adminGet<T>(token, path, params)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((e) => !cancelled && setState((s) => ({ data: s.data, error: e instanceof ApiError ? e.message : "Could not load this data.", loading: false })));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: state.data, error: state.error, loading: state.loading, reload };
}

export function DataState({ loading, error, empty, onRetry, children }: { loading: boolean; error: string | null; empty?: boolean; onRetry?: () => void; children: ReactNode }) {
  if (error) {
    return (
      <p className={styles.error} role="alert" data-testid="state-error">
        {error}{" "}
        {onRetry && (
          <button type="button" className={styles.linkButton} onClick={onRetry}>
            Try again
          </button>
        )}
      </p>
    );
  }
  if (loading) return <p className={styles.muted} role="status">Loading…</p>;
  if (empty) return <p className={styles.empty} data-testid="state-empty">Nothing to show for these filters.</p>;
  return <>{children}</>;
}

export function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <div className={styles.pager}>
      <span className={styles.muted}>{total} result{total === 1 ? "" : "s"}</span>
      <button type="button" className={styles.secondary} disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span aria-live="polite">Page {page} of {pages}</span>
      <button type="button" className={styles.secondary} disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

export const RANGES: [string, string][] = [
  ["today", "Today"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["90d", "Last 90 days"],
  ["this_month", "This month"], ["last_month", "Last month"], ["custom", "Custom"],
];

export interface RangeValue {
  range: string;
  start: string;
  end: string;
}

export function rangeParams(r: RangeValue): Query {
  return r.range === "custom" ? { range: "custom", start: r.start, end: r.end } : { range: r.range };
}

export function RangeBar({ value, onChange }: { value: RangeValue; onChange: (v: RangeValue) => void }) {
  return (
    <div className={styles.filters}>
      <label>
        Period
        <select value={value.range} onChange={(e) => onChange({ ...value, range: e.target.value })}>
          {RANGES.map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
      </label>
      {value.range === "custom" && (
        <>
          <label>
            From
            <input type="date" value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} />
          </label>
          <label>
            To
            <input type="date" value={value.end} onChange={(e) => onChange({ ...value, end: e.target.value })} />
          </label>
        </>
      )}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className={styles.stat}>
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue}>{value}</div>
      {hint && <div className={styles.statHint}>{hint}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "good" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  const cls = tone === "good" ? styles.badgeGood : tone === "warn" ? styles.badgeWarn : tone === "bad" ? styles.badgeBad : "";
  return <span className={`${styles.badge} ${cls}`}>{children}</span>;
}

export interface ActionSpec {
  title: string;
  description: string;
  submitLabel: string;
  extra?: { label: string; type: "number" | "text"; initial?: string; min?: number; max?: number };
  run: (reason: string, extra: string) => Promise<unknown>;
  danger?: boolean;
}

/** Every admin change goes through this: a reason is required and the action must be confirmed. */
export function ActionDialog({ spec, onClose, onDone }: { spec: ActionSpec; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [extra, setExtra] = useState(spec.extra?.initial ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await spec.run(reason.trim(), extra);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The action failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={spec.title}>
      <div className={styles.dialog}>
        <h3>{spec.title}</h3>
        <p className={styles.muted}>{spec.description}</p>
        {spec.extra && (
          <label>
            {spec.extra.label}
            <input type={spec.extra.type} value={extra} min={spec.extra.min} max={spec.extra.max} onChange={(e) => setExtra(e.target.value)} />
          </label>
        )}
        <label>
          Reason (recorded in the audit log)
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
        </label>
        <label className={styles.check}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I understand and confirm this action
        </label>
        {error && <p className={styles.error} role="alert" data-testid="dialog-error">{error}</p>}
        <div className={styles.dialogActions}>
          <button type="button" className={styles.secondary} onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className={spec.danger ? styles.danger : styles.primary} disabled={busy || !reason.trim() || !confirmed} onClick={submit}>
            {busy ? "Working…" : spec.submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function BarChart({ points, label }: { points: { date: string; value: number }[]; label: string }) {
  const max = Math.max(1, ...points.map((p) => p.value));
  const w = 600;
  const h = 140;
  const bw = w / Math.max(points.length, 1);
  return (
    <svg viewBox={`0 0 ${w} ${h + 18}`} role="img" aria-label={label} className={styles.chart}>
      {points.map((p, i) => {
        const bh = (p.value / max) * h;
        return (
          <rect key={p.date} x={i * bw + 1} y={h - bh} width={Math.max(bw - 2, 1)} height={bh} className={styles.bar}>
            <title>{`${p.date}: ${(p.value / 100).toFixed(2)}`}</title>
          </rect>
        );
      })}
      <text x="0" y={h + 14} className={styles.axis}>{points[0]?.date ?? ""}</text>
      <text x={w} y={h + 14} textAnchor="end" className={styles.axis}>{points[points.length - 1]?.date ?? ""}</text>
    </svg>
  );
}
