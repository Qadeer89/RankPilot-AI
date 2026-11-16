"use client";

import { useState } from "react";
import { getToken } from "@/lib/auth";
import { adminSend, formatMoneyMap, type MoneyMap, type Paged } from "@/lib/adminApi";
import { formatDate } from "@/lib/billingFormat";
import {
  ActionDialog, BarChart, Badge, DataState, Pager, RangeBar, Stat, rangeParams, useAdminData,
  type ActionSpec, type RangeValue,
} from "./parts";
import styles from "./admin.module.css";

const token = () => getToken() ?? "";
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "—");

function tone(status: string): "good" | "warn" | "bad" | "neutral" {
  if (["active", "trialing", "paid", "processed", "ok", "connected"].includes(status)) return "good";
  if (["past_due", "cancelled", "partially_refunded", "warning", "paused", "unknown", "received"].includes(status)) return "warn";
  if (["disabled", "failed", "expired", "refunded", "unpaid", "error", "rejected"].includes(status)) return "bad";
  return "neutral";
}

function Filters({ children }: { children: React.ReactNode }) {
  return <div className={styles.filters}>{children}</div>;
}

// ------------------------------------------------------------------ Overview

interface Overview {
  users: { total: number; new: number; active: number; suspended: number };
  projects: { total: number; subscribed: number; unsubscribed: number; suspended: number };
  subscriptions: { by_status: Record<string, number>; by_interval_live: Record<string, number>; total: number; complimentary: number };
  revenue: {
    gross_collected_cents: MoneyMap; refunds_cents: MoneyMap; net_cents: MoneyMap; new_subscription_revenue_cents: MoneyMap;
    failed_payments: { count: number }; recovered_payments: number;
    recurring: { mrr_cents: MoneyMap; arr_cents: MoneyMap; paying_subscriptions: number };
  };
  trials: { started: number; active: number; conversion_rate: number | null };
  replacements: { total: number; admin_overrides: number };
}

export function OverviewSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const { data, loading, error, reload } = useAdminData<Overview>("overview", rangeParams(range));
  return (
    <section aria-label="Overview">
      <RangeBar value={range} onChange={setRange} />
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <h3>Users</h3>
            <div className={styles.stats}>
              <Stat label="Total users" value={data.users.total} />
              <Stat label="New in period" value={data.users.new} />
              <Stat label="Active" value={data.users.active} />
              <Stat label="Suspended" value={data.users.suspended} />
            </div>
            <h3>Projects &amp; subscriptions</h3>
            <div className={styles.stats}>
              <Stat label="Projects" value={data.projects.total} />
              <Stat label="Subscribed" value={data.projects.subscribed} />
              <Stat label="Unsubscribed" value={data.projects.unsubscribed} />
              <Stat label="Complimentary" value={data.subscriptions.complimentary} hint="Free access, not revenue" />
              {Object.entries(data.subscriptions.by_status).map(([k, v]) => (
                <Stat key={k} label={`Subscriptions: ${k.replace("_", " ")}`} value={v} />
              ))}
              <Stat label="Live monthly" value={data.subscriptions.by_interval_live.month ?? 0} />
              <Stat label="Live annual" value={data.subscriptions.by_interval_live.year ?? 0} />
            </div>
            <h3>Recurring revenue (now)</h3>
            <div className={styles.stats}>
              <Stat label="MRR" value={formatMoneyMap(data.revenue.recurring.mrr_cents)} hint="Active + past due. Trials excluded. Annual ÷ 12." />
              <Stat label="ARR" value={formatMoneyMap(data.revenue.recurring.arr_cents)} hint="MRR × 12" />
              <Stat label="Paying subscriptions" value={data.revenue.recurring.paying_subscriptions} />
            </div>
            <h3>Cash collected (selected period)</h3>
            <div className={styles.stats}>
              <Stat label="Gross collected" value={formatMoneyMap(data.revenue.gross_collected_cents)} hint="Cash, not MRR" />
              <Stat label="Refunds" value={formatMoneyMap(data.revenue.refunds_cents)} />
              <Stat label="Net" value={formatMoneyMap(data.revenue.net_cents)} />
              <Stat label="New-subscription revenue" value={formatMoneyMap(data.revenue.new_subscription_revenue_cents)} />
              <Stat label="Failed payments" value={data.revenue.failed_payments.count} />
              <Stat label="Recovered payments" value={data.revenue.recovered_payments} />
            </div>
            <h3>Trials &amp; replacements</h3>
            <div className={styles.stats}>
              <Stat label="Trials started" value={data.trials.started} />
              <Stat label="Trials running" value={data.trials.active} />
              <Stat label="Trial → paid" value={pct(data.trials.conversion_rate)} hint="Among finished trials" />
              <Stat label="Replacements" value={data.replacements.total} />
              <Stat label="Admin exceptions used" value={data.replacements.admin_overrides} />
            </div>
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Users

interface UserRow { id: string; email: string; status: string; email_verified: boolean; created_at: string; workspaces: number; projects: number }

export function UsersSection() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("created_at");
  const [action, setAction] = useState<ActionSpec | null>(null);
  const { data, loading, error, reload } = useAdminData<Paged<UserRow>>("users", { q, status, page, sort, dir: sort === "email" ? "asc" : "desc" });
  function act(u: UserRow, verb: "suspend" | "reactivate") {
    setAction({
      title: `${verb === "suspend" ? "Suspend" : "Reactivate"} ${u.email}`,
      description: verb === "suspend" ? "The user can no longer sign in. Nothing is deleted and the account can be reactivated." : "The user can sign in again.",
      submitLabel: verb === "suspend" ? "Suspend user" : "Reactivate user", danger: verb === "suspend",
      run: (reason) => adminSend(token(), "POST", `users/${u.id}/${verb}`, { reason, confirm: true }),
    });
  }
  return (
    <section aria-label="Users">
      <Filters>
        <label>Search email<input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="name@example.com" /></label>
        <label>Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option><option value="active">Active</option><option value="disabled">Suspended</option></select></label>
        <label>Sort<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="created_at">Newest</option><option value="email">Email</option></select></label>
      </Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>Email</th><th>Status</th><th>Verified</th><th>Projects</th><th>Joined</th><th /></tr></thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id}>
                    <td>{u.email}</td>
                    <td><Badge tone={tone(u.status)}>{u.status === "disabled" ? "suspended" : u.status}</Badge></td>
                    <td>{u.email_verified ? "Yes" : "No"}</td>
                    <td>{u.projects}</td>
                    <td>{formatDate(u.created_at)}</td>
                    <td>
                      {u.status === "active"
                        ? <button type="button" className={styles.secondary} onClick={() => act(u, "suspend")}>Suspend</button>
                        : <button type="button" className={styles.secondary} onClick={() => act(u, "reactivate")}>Reactivate</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
      {action && <ActionDialog spec={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />}
    </section>
  );
}

// ------------------------------------------------------------------ Projects

interface ProjectRow { id: string; name: string; hostname: string; owner_email: string | null; status: string; subscription_status: string | null; subscription_interval: string | null; complimentary: boolean }

export function ProjectsSection() {
  const [q, setQ] = useState("");
  const [subscribed, setSubscribed] = useState("");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState<ActionSpec | null>(null);
  const { data, loading, error, reload } = useAdminData<Paged<ProjectRow>>("projects", { q, subscribed, page });
  function suspend(p: ProjectRow, verb: "suspend" | "reactivate") {
    setAction({
      title: `${verb === "suspend" ? "Suspend processing for" : "Reactivate"} ${p.hostname}`,
      description: verb === "suspend" ? "Crawls, AI and scheduled work stop. The project and all its data are kept." : "Processing resumes.",
      submitLabel: verb === "suspend" ? "Suspend processing" : "Reactivate", danger: verb === "suspend",
      run: (reason) => adminSend(token(), "POST", `projects/${p.id}/${verb}`, { reason, confirm: true }),
    });
  }
  function complimentary(p: ProjectRow) {
    setAction({
      title: `Grant complimentary access to ${p.hostname}`,
      description: "Free access for this project. It is not revenue and never counts toward MRR, ARR or cash collected.",
      submitLabel: "Grant access", extra: { label: "Days (leave empty for no end date)", type: "number", initial: "", min: 1, max: 3650 },
      run: (reason, extra) => adminSend(token(), "POST", `projects/${p.id}/complimentary`, { reason, confirm: true, days: extra ? Number(extra) : null }),
    });
  }
  return (
    <section aria-label="Projects">
      <Filters>
        <label>Search<input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="domain or name" /></label>
        <label>Subscription<select value={subscribed} onChange={(e) => { setSubscribed(e.target.value); setPage(1); }}><option value="">All</option><option value="true">Subscribed</option><option value="false">No subscription</option></select></label>
      </Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>Project</th><th>Owner</th><th>State</th><th>Subscription</th><th /></tr></thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td>{p.hostname}</td>
                    <td>{p.owner_email ?? "—"}</td>
                    <td><Badge tone={p.status === "active" ? "good" : "warn"}>{p.status === "paused" ? "suspended" : p.status}</Badge></td>
                    <td>
                      {p.subscription_status ? <Badge tone={tone(p.subscription_status)}>{p.complimentary ? "complimentary" : `${p.subscription_status} · ${p.subscription_interval}`}</Badge> : <span className={styles.muted}>None</span>}
                    </td>
                    <td className={styles.rowActions}>
                      {p.status === "active"
                        ? <button type="button" className={styles.secondary} onClick={() => suspend(p, "suspend")}>Suspend</button>
                        : <button type="button" className={styles.secondary} onClick={() => suspend(p, "reactivate")}>Reactivate</button>}
                      {!p.subscription_status && <button type="button" className={styles.secondary} onClick={() => complimentary(p)}>Grant free access</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
      {action && <ActionDialog spec={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />}
    </section>
  );
}

// ------------------------------------------------------------------ Subscriptions

interface SubRow {
  id: string; status: string; provider: string; interval: string; price_cents: number; currency: string; customer_email: string | null;
  hostname: string | null; trial_ends_at: string | null; renews_at: string | null; created_at: string; replacements_used: number; replacement_limit: number;
  provider_subscription_id: string | null;
}
interface SubDetail extends SubRow {
  payments: PaymentRow[]; events: EventRow[];
  replacements: { sequence: number; admin_override: boolean; reason: string | null; created_at: string }[];
}

export function SubscriptionsSection() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [interval, setInterval] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("created_at");
  const [openId, setOpenId] = useState<string | null>(null);
  const { data, loading, error, reload } = useAdminData<Paged<SubRow>>("subscriptions", { q, status, interval, page, sort, dir: "desc" });
  return (
    <section aria-label="Subscriptions">
      <Filters>
        <label>Search<input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="email, domain or provider id" /></label>
        <label>Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{["trialing", "active", "past_due", "cancelled", "expired", "refunded", "unpaid", "paused"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</select></label>
        <label>Interval<select value={interval} onChange={(e) => { setInterval(e.target.value); setPage(1); }}><option value="">All</option><option value="month">Monthly</option><option value="year">Annual</option></select></label>
        <label>Sort<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="created_at">Newest</option><option value="price">Price</option><option value="renews_at">Renewal date</option></select></label>
      </Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>Project</th><th>Customer</th><th>Plan</th><th>Status</th><th>Renews / trial ends</th><th /></tr></thead>
              <tbody>
                {data.items.map((s) => (
                  <tr key={s.id}>
                    <td>{s.hostname ?? "—"}</td>
                    <td>{s.customer_email ?? "—"}</td>
                    <td>{s.provider === "complimentary" ? "Complimentary" : `${s.interval === "month" ? "Monthly" : "Annual"} · ${formatMoneyMap({ [s.currency]: s.price_cents })}`}</td>
                    <td><Badge tone={tone(s.status)}>{s.status.replace("_", " ")}</Badge></td>
                    <td>{formatDate(s.status === "trialing" ? s.trial_ends_at : s.renews_at)}</td>
                    <td><button type="button" className={styles.secondary} onClick={() => setOpenId(s.id)}>Details</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
      {openId && <SubscriptionDetail id={openId} onClose={() => { setOpenId(null); reload(); }} />}
    </section>
  );
}

function SubscriptionDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, loading, error, reload } = useAdminData<SubDetail>(`subscriptions/${id}`);
  const [action, setAction] = useState<ActionSpec | null>(null);
  function grantException() {
    setAction({
      title: "Grant one extra project replacement",
      description: "Adds one replacement to this subscription's lifetime allowance. Nothing else changes.",
      submitLabel: "Grant exception",
      run: (reason) => adminSend(token(), "POST", `subscriptions/${id}/replacement-exception`, { reason, confirm: true }),
    });
  }
  function extend() {
    setAction({
      title: "Extend complimentary access",
      description: "Adds days to the end of this complimentary access. (Provider-billed trials are extended in the payment provider.)",
      submitLabel: "Extend", extra: { label: "Days to add", type: "number", initial: "7", min: 1, max: 90 },
      run: (reason, days) => adminSend(token(), "POST", `subscriptions/${id}/extend-trial`, { reason, confirm: true, days: Number(days) }),
    });
  }
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Subscription details">
      <div className={`${styles.dialog} ${styles.wide}`}>
        <h3>Subscription details</h3>
        <DataState loading={loading && !data} error={error} onRetry={reload}>
          {data && (
            <>
              <dl className={styles.facts}>
                <dt>Project</dt><dd>{data.hostname ?? "—"}</dd>
                <dt>Customer</dt><dd>{data.customer_email ?? "—"}</dd>
                <dt>Status</dt><dd><Badge tone={tone(data.status)}>{data.status.replace("_", " ")}</Badge></dd>
                <dt>Provider reference</dt><dd>{data.provider_subscription_id ?? "none (not provider-billed)"}</dd>
                <dt>Replacements</dt><dd>{data.replacements_used} of {data.replacement_limit} used</dd>
              </dl>
              <h4>Payments</h4>
              {data.payments.length === 0 ? <p className={styles.muted}>No payments recorded.</p> : (
                <table className={styles.table}><tbody>{data.payments.map((p) => (
                  <tr key={p.id}><td>{when(p.paid_at ?? p.created_at)}</td><td>{formatMoneyMap({ [p.currency]: p.amount_cents })}</td><td><Badge tone={tone(p.status)}>{p.status.replace("_", " ")}</Badge></td><td>{p.test_mode ? "test" : "live"}</td></tr>
                ))}</tbody></table>
              )}
              <h4>Webhook history</h4>
              {data.events.length === 0 ? <p className={styles.muted}>No events.</p> : (
                <table className={styles.table}><tbody>{data.events.map((e) => (
                  <tr key={e.id}><td>{when(e.received_at)}</td><td>{e.event_name}</td><td><Badge tone={tone(e.status)}>{e.status}</Badge></td></tr>
                ))}</tbody></table>
              )}
              <h4>Replacements</h4>
              {data.replacements.length === 0 ? <p className={styles.muted}>None yet.</p> : (
                <ul>{data.replacements.map((r) => <li key={r.sequence}>#{r.sequence} · {when(r.created_at)}{r.admin_override ? " · admin exception" : ""}{r.reason ? ` · ${r.reason}` : ""}</li>)}</ul>
              )}
              <div className={styles.dialogActions}>
                <button type="button" className={styles.secondary} onClick={grantException}>Grant replacement exception</button>
                {data.provider === "complimentary" && <button type="button" className={styles.secondary} onClick={extend}>Extend access</button>}
              </div>
            </>
          )}
        </DataState>
        <div className={styles.dialogActions}><button type="button" className={styles.primary} onClick={onClose}>Close</button></div>
      </div>
      {action && <ActionDialog spec={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />}
    </div>
  );
}

// ------------------------------------------------------------------ Payments

interface PaymentRow { id: string; amount_cents: number; currency: string; status: string; refunded_cents: number; billing_reason: string | null; interval: string | null; paid_at: string | null; created_at: string; test_mode: boolean }

export function PaymentsSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const [status, setStatus] = useState("");
  const [interval, setInterval] = useState("");
  const [includeTest, setIncludeTest] = useState(false);
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useAdminData<Paged<PaymentRow> & { refund_note: string }>("payments", { ...rangeParams(range), status, interval, include_test: includeTest, page });
  return (
    <section aria-label="Payments">
      <RangeBar value={range} onChange={(r) => { setRange(r); setPage(1); }} />
      <Filters>
        <label>Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{["paid", "failed", "pending", "refunded", "partially_refunded"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</select></label>
        <label>Interval<select value={interval} onChange={(e) => { setInterval(e.target.value); setPage(1); }}><option value="">All</option><option value="month">Monthly</option><option value="year">Annual</option></select></label>
        <label className={styles.check}><input type="checkbox" checked={includeTest} onChange={(e) => setIncludeTest(e.target.checked)} />Include test-mode payments</label>
      </Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>Date</th><th>Amount</th><th>Status</th><th>Type</th><th>Refunded</th><th>Mode</th></tr></thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td>{when(p.paid_at ?? p.created_at)}</td>
                    <td>{formatMoneyMap({ [p.currency]: p.amount_cents })}</td>
                    <td><Badge tone={tone(p.status)}>{p.status.replace("_", " ")}</Badge></td>
                    <td>{p.billing_reason ?? "—"} · {p.interval ?? "—"}</td>
                    <td>{p.refunded_cents ? formatMoneyMap({ [p.currency]: p.refunded_cents }) : "—"}</td>
                    <td>{p.test_mode ? "test" : "live"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className={styles.muted}>{data.refund_note}</p>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Revenue

interface Revenue {
  gross_collected_cents: MoneyMap; refunds_cents: MoneyMap; net_cents: MoneyMap; new_subscription_revenue_cents: MoneyMap;
  by_interval_cents: Record<string, MoneyMap>; failed_payments: { count: number; amount_cents: MoneyMap }; recovered_payments: number;
  churn: { cancelled: number; base: number; rate: number | null };
  series: { date: string; collected_cents: MoneyMap }[];
  recurring: { mrr_cents: MoneyMap; arr_cents: MoneyMap; past_due_mrr_cents: MoneyMap; paying_subscriptions: number };
}

export function RevenueSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const { data, loading, error, reload } = useAdminData<Revenue>("revenue", rangeParams(range));
  const currencies = data ? Array.from(new Set(data.series.flatMap((p) => Object.keys(p.collected_cents)))) : [];
  const chartCurrency = currencies[0] ?? "USD";
  return (
    <section aria-label="Revenue analytics">
      <RangeBar value={range} onChange={setRange} />
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <h3>Recurring (point in time)</h3>
            <div className={styles.stats}>
              <Stat label="MRR" value={formatMoneyMap(data.recurring.mrr_cents)} hint="Active + past due; annual ÷ 12; trials excluded" />
              <Stat label="ARR" value={formatMoneyMap(data.recurring.arr_cents)} hint="MRR × 12" />
              <Stat label="Past-due MRR at risk" value={formatMoneyMap(data.recurring.past_due_mrr_cents)} />
              <Stat label="Paying subscriptions" value={data.recurring.paying_subscriptions} />
            </div>
            <h3>Cash collected in period</h3>
            <div className={styles.stats}>
              <Stat label="Gross collected" value={formatMoneyMap(data.gross_collected_cents)} />
              <Stat label="Refunds" value={formatMoneyMap(data.refunds_cents)} />
              <Stat label="Net" value={formatMoneyMap(data.net_cents)} />
              <Stat label="New-subscription revenue" value={formatMoneyMap(data.new_subscription_revenue_cents)} />
              <Stat label="Monthly plans" value={formatMoneyMap(data.by_interval_cents.month)} />
              <Stat label="Annual plans" value={formatMoneyMap(data.by_interval_cents.year)} />
              <Stat label="Failed payments" value={`${data.failed_payments.count} · ${formatMoneyMap(data.failed_payments.amount_cents)}`} />
              <Stat label="Recovered" value={data.recovered_payments} />
              <Stat label="Churn" value={pct(data.churn.rate)} hint={`${data.churn.cancelled} cancelled of ${data.churn.base} paying`} />
            </div>
            <h3>Daily cash collected ({chartCurrency})</h3>
            <BarChart label={`Daily cash collected in ${chartCurrency}`} points={data.series.map((p) => ({ date: p.date, value: p.collected_cents[chartCurrency] ?? 0 }))} />
            {currencies.length > 1 && <p className={styles.muted}>Several currencies were collected; the chart shows {chartCurrency} only. Currencies are never added together.</p>}
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Trials & replacements

interface Trials { started: number; active: number; converted: number; cancelled: number; expired: number; finished: number; conversion_rate: number | null; ending_within_3_days: number }

export function TrialsSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const { data, loading, error, reload } = useAdminData<Trials>("trials", rangeParams(range));
  return (
    <section aria-label="Trials">
      <RangeBar value={range} onChange={setRange} />
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <div className={styles.stats}>
            <Stat label="Trials started" value={data.started} />
            <Stat label="Running" value={data.active} />
            <Stat label="Converted" value={data.converted} />
            <Stat label="Cancelled" value={data.cancelled} />
            <Stat label="Expired" value={data.expired} />
            <Stat label="Conversion rate" value={pct(data.conversion_rate)} hint="Converted ÷ finished trials" />
            <Stat label="Ending within 3 days" value={data.ending_within_3_days} />
          </div>
        )}
      </DataState>
    </section>
  );
}

interface Replacements {
  summary: { total: number; admin_overrides: number; subscriptions_with_allowance_used: number; subscriptions_with_exception_granted: number };
  items: { id: string; sequence: number; from: string | null; to: string | null; admin_override: boolean; reason: string | null; created_at: string }[];
  page: number; pages: number; total: number;
}

export function ReplacementsSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useAdminData<Replacements>("replacements", { ...rangeParams(range), page });
  return (
    <section aria-label="Project replacements">
      <RangeBar value={range} onChange={(r) => { setRange(r); setPage(1); }} />
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <div className={styles.stats}>
              <Stat label="Replacements" value={data.summary.total} />
              <Stat label="Admin exceptions used" value={data.summary.admin_overrides} />
              <Stat label="Allowance used up" value={data.summary.subscriptions_with_allowance_used} />
              <Stat label="Exceptions granted" value={data.summary.subscriptions_with_exception_granted} />
            </div>
            {data.items.length === 0 ? <p className={styles.empty} data-testid="state-empty">No replacements in this period.</p> : (
              <>
                <table className={styles.table}>
                  <thead><tr><th>When</th><th>From</th><th>To</th><th>#</th><th>Exception</th></tr></thead>
                  <tbody>{data.items.map((r) => <tr key={r.id}><td>{when(r.created_at)}</td><td>{r.from ?? "—"}</td><td>{r.to ?? "—"}</td><td>{r.sequence}</td><td>{r.admin_override ? `Yes${r.reason ? ` · ${r.reason}` : ""}` : "No"}</td></tr>)}</tbody>
                </table>
                <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
              </>
            )}
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ AI costs

interface AiCosts {
  cost_basis: string; runs: number; failed_runs: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number;
  by_project: { website_id: string; name: string; runs: number; estimated_cost_usd: number; tokens: number }[];
  by_model: { model: string; runs: number; estimated_cost_usd: number }[];
  daily: { date: string; estimated_cost_usd: number; over_threshold: boolean }[]; daily_warning_usd: number;
}

export function AiCostsSection({ range, setRange }: { range: RangeValue; setRange: (r: RangeValue) => void }) {
  const { data, loading, error, reload } = useAdminData<AiCosts>("ai-costs", rangeParams(range));
  return (
    <section aria-label="AI usage and costs">
      <RangeBar value={range} onChange={setRange} />
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <p className={styles.note}>Costs are <strong>estimates</strong> RankPilot computes from token counts; they are not a provider invoice. Chat-assistant and embedding calls are not included.</p>
            <div className={styles.stats}>
              <Stat label="Estimated cost" value={`$${data.estimated_cost_usd.toFixed(2)}`} />
              <Stat label="AI runs" value={data.runs} />
              <Stat label="Failed runs" value={data.failed_runs} />
              <Stat label="Input tokens" value={data.input_tokens.toLocaleString()} />
              <Stat label="Output tokens" value={data.output_tokens.toLocaleString()} />
            </div>
            <h3>By project</h3>
            {data.by_project.length === 0 ? <p className={styles.empty} data-testid="state-empty">No AI runs in this period.</p> : (
              <table className={styles.table}><thead><tr><th>Project</th><th>Runs</th><th>Tokens</th><th>Est. cost</th></tr></thead>
                <tbody>{data.by_project.map((p) => <tr key={p.website_id}><td>{p.name}</td><td>{p.runs}</td><td>{p.tokens.toLocaleString()}</td><td>${p.estimated_cost_usd.toFixed(2)}</td></tr>)}</tbody></table>
            )}
            <h3>Days above ${data.daily_warning_usd.toFixed(2)}</h3>
            {data.daily.filter((d) => d.over_threshold).length === 0 ? <p className={styles.muted}>No day exceeded the threshold.</p> : (
              <ul>{data.daily.filter((d) => d.over_threshold).map((d) => <li key={d.date}><Badge tone="warn">over</Badge> {d.date}: ${d.estimated_cost_usd.toFixed(2)}</li>)}</ul>
            )}
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Integrations & webhooks

interface EventRow { id: string; event_name: string | null; status: string; attempts?: number; error?: string | null; received_at: string; processed_at?: string | null; test_mode?: boolean }

export function WebhooksSection() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState<ActionSpec | null>(null);
  const { data, loading, error, reload } = useAdminData<Paged<EventRow> & { counts: Record<string, number> }>("webhooks", { status, page });
  function retry(e: EventRow) {
    setAction({
      title: `Retry ${e.event_name}`, description: "Re-applies this stored, signature-verified event. Safe to repeat.", submitLabel: "Retry event",
      run: (reason) => adminSend(token(), "POST", `webhooks/${e.id}/retry`, { reason, confirm: true }),
    });
  }
  return (
    <section aria-label="Integrations and webhooks">
      <Filters>
        <label>Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{["received", "processed", "ignored", "failed", "rejected"].map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
      </Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <div className={styles.stats}>{Object.entries(data.counts).map(([k, v]) => <Stat key={k} label={k} value={v} />)}</div>
            <table className={styles.table}>
              <thead><tr><th>Received</th><th>Event</th><th>Status</th><th>Attempts</th><th>Error</th><th /></tr></thead>
              <tbody>{data.items.map((e) => (
                <tr key={e.id}><td>{when(e.received_at)}</td><td>{e.event_name ?? "—"}</td><td><Badge tone={tone(e.status)}>{e.status}</Badge></td><td>{e.attempts}</td><td>{e.error ?? "—"}</td>
                  <td>{e.status === "failed" && <button type="button" className={styles.secondary} onClick={() => retry(e)}>Retry</button>}</td></tr>
              ))}</tbody>
            </table>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
      {action && <ActionDialog spec={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />}
    </section>
  );
}

// ------------------------------------------------------------------ Health

interface Health { overall: string; checked_at: string; checks: { name: string; state: string; detail: string }[] }

export function HealthSection() {
  const { data, loading, error, reload } = useAdminData<Health>("health");
  return (
    <section aria-label="System health">
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <p>Overall: <Badge tone={tone(data.overall)}>{data.overall}</Badge> <span className={styles.muted}>checked {when(data.checked_at)}</span>{" "}
              <button type="button" className={styles.secondary} onClick={reload}>Refresh</button></p>
            <table className={styles.table}>
              <thead><tr><th>Check</th><th>State</th><th>Detail</th></tr></thead>
              <tbody>{data.checks.map((c) => <tr key={c.name}><td>{c.name.replace(/_/g, " ")}</td><td><Badge tone={tone(c.state)}>{c.state}</Badge></td><td>{c.detail}</td></tr>)}</tbody>
            </table>
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Audit logs

interface AuditRow { id: string; action: string; admin: string | null; target_type: string; target_id: string; at: string; reason: string | null; before: unknown; after: unknown }

export function AuditSection() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useAdminData<Paged<AuditRow>>("audit-logs", { q, page });
  return (
    <section aria-label="Audit logs">
      <Filters><label>Target id<input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label></Filters>
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>When</th><th>Admin</th><th>Action</th><th>Target</th><th>Reason</th><th>Before → after</th></tr></thead>
              <tbody>{data.items.map((a) => (
                <tr key={a.id}><td>{when(a.at)}</td><td>{a.admin ?? "system"}</td><td>{a.action}</td><td>{a.target_type} {a.target_id.slice(0, 8)}</td><td>{a.reason ?? "—"}</td>
                  <td><code>{a.before ? JSON.stringify(a.before) : "—"} → {a.after ? JSON.stringify(a.after) : "—"}</code></td></tr>
              ))}</tbody>
            </table>
            <p className={styles.muted}>Audit records are append-only: they cannot be edited or deleted here.</p>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </section>
  );
}

// ------------------------------------------------------------------ Settings

interface SettingItem { key: string; label: string; description: string; value: number | string; default: number | string; source: string; sensitive: boolean }

export function SettingsSection() {
  const { data, loading, error, reload } = useAdminData<{ items: SettingItem[]; notes: string[] }>("settings");
  const [action, setAction] = useState<ActionSpec | null>(null);
  function edit(s: SettingItem) {
    setAction({
      title: `Change ${s.label}`, description: s.description, submitLabel: "Save change",
      extra: { label: "New value", type: typeof s.value === "number" ? "number" : "text", initial: String(s.value) },
      run: (reason, value) => adminSend(token(), "PUT", `settings/${s.key}`, { reason, confirm: true, value: typeof s.value === "number" ? Number(value) : value }),
    });
  }
  function reset(s: SettingItem) {
    setAction({
      title: `Reset ${s.label}`, description: "Goes back to the value from the server environment.", submitLabel: "Reset",
      run: (reason) => adminSend(token(), "DELETE", `settings/${s.key}`, { reason, confirm: true }),
    });
  }
  return (
    <section aria-label="Settings">
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <ul className={styles.notes}>{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            <table className={styles.table}>
              <thead><tr><th>Setting</th><th>Value</th><th>Source</th><th /></tr></thead>
              <tbody>{data.items.map((s) => (
                <tr key={s.key}><td>{s.label}<div className={styles.muted}>{s.description}</div></td><td><strong>{String(s.value)}</strong></td><td>{s.source}</td>
                  <td className={styles.rowActions}><button type="button" className={styles.secondary} onClick={() => edit(s)}>Change</button>
                    {s.source === "admin override" && <button type="button" className={styles.secondary} onClick={() => reset(s)}>Reset</button>}</td></tr>
              ))}</tbody>
            </table>
          </>
        )}
      </DataState>
      {action && <ActionDialog spec={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />}
    </section>
  );
}
