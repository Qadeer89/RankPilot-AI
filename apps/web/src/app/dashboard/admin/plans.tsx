"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { adminSend, type Paged } from "@/lib/adminApi";
import { formatMoney } from "@/lib/billingFormat";
import { Badge, DataState, Pager, useAdminData } from "./parts";
import styles from "./admin.module.css";

const token = () => getToken() ?? "";

interface PlanRow {
  id: string; code: string; name: string; description: string | null; interval: "month" | "year"; amount_cents: number | null; currency: string;
  trial_days: number; max_projects: number | null; max_websites: number | null; max_domains_per_project: number | null;
  entitlements: Record<string, boolean>; limits: Record<string, number>; is_active: boolean; is_public: boolean; is_approved: boolean; is_test_config: boolean;
  paddle_product_id: string | null; paddle_price_id: string | null; paddle_price_id_no_trial: string | null; publicly_visible: boolean; sellable: boolean; subscriptions: number;
}
interface PlansData {
  items: PlanRow[]; features: Record<string, string>; usage_limits: Record<string, string>;
  paddle: { environment: string; provider_active: boolean; api_key_set: boolean; client_token_set: boolean; webhook_secret_set: boolean; webhook_url: string };
}

const num = (v: string) => (v.trim() === "" ? null : Number(v));

function PlanForm({ data, plan, onClose, onDone }: { data: PlansData; plan: PlanRow | null; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({
    code: plan?.code ?? "", name: plan?.name ?? "", description: plan?.description ?? "", interval: plan?.interval ?? "month",
    amount: plan?.amount_cents != null ? String(plan.amount_cents) : "", trial_days: String(plan?.trial_days ?? 0),
    max_projects: plan?.max_projects != null ? String(plan.max_projects) : "", max_websites: plan?.max_websites != null ? String(plan.max_websites) : "",
    product: plan?.paddle_product_id ?? "", price: plan?.paddle_price_id ?? "", price_nt: plan?.paddle_price_id_no_trial ?? "",
    is_active: plan?.is_active ?? false, is_public: plan?.is_public ?? false, is_approved: plan?.is_approved ?? false, is_test_config: plan?.is_test_config ?? true,
    reason: "", confirm: false,
  });
  const [features, setFeatures] = useState<Record<string, "default" | "on" | "off">>(
    Object.fromEntries(Object.keys(data.features).map((k) => [k, plan?.entitlements[k] === true ? "on" : plan?.entitlements[k] === false ? "off" : "default"])),
  );
  const [limits, setLimits] = useState<Record<string, string>>(Object.fromEntries(Object.keys(data.usage_limits).map((k) => [k, plan?.limits[k] != null ? String(plan.limits[k]) : ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string, v: string | boolean) => setF((s) => ({ ...s, [k]: v }));

  async function submit() {
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      name: f.name, description: f.description, billing_interval: f.interval, trial_days: num(f.trial_days) ?? 0,
      max_projects: num(f.max_projects), max_websites: num(f.max_websites),
      paddle_product_id: f.product, paddle_price_id: f.price, paddle_price_id_no_trial: f.price_nt,
      entitlements: Object.fromEntries(Object.entries(features).filter(([, v]) => v !== "default").map(([k, v]) => [k, v === "on"])),
      limits: Object.fromEntries(Object.entries(limits).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, Number(v)])),
      is_active: f.is_active, is_public: f.is_public, is_test_config: f.is_test_config, reason: f.reason.trim(), confirm: f.confirm,
    };
    if (f.amount.trim() === "") body.clear_amount = true; else body.amount_cents = Number(f.amount);
    try {
      if (plan) {
        body.is_approved = f.is_approved;
        await adminSend(token(), "PATCH", `billing/plans/${plan.id}`, body);
      } else {
        body.code = f.code;
        await adminSend(token(), "POST", "billing/plans", body);
      }
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the plan.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={plan ? `Edit ${plan.name}` : "New plan"}>
      <div className={styles.dialog} style={{ maxHeight: "90vh", overflow: "auto" }}>
        <h3>{plan ? `Edit plan: ${plan.code}` : "New plan"}</h3>
        <p className={styles.muted}>Prices are never defaulted. Leave the price empty until you have decided it. Approving a plan makes it visible and purchasable in Live.</p>
        {!plan && <label>Code (permanent)<input value={f.code} onChange={(e) => set("code", e.target.value)} /></label>}
        <label>Name<input value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>Description<input value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
        <label>Interval<select value={f.interval} onChange={(e) => set("interval", e.target.value)}><option value="month">Monthly</option><option value="year">Yearly</option></select></label>
        <label>Price in minor units (cents). Empty = not decided<input inputMode="numeric" value={f.amount} onChange={(e) => set("amount", e.target.value)} /></label>
        <label>Trial days (0 = none)<input inputMode="numeric" value={f.trial_days} onChange={(e) => set("trial_days", e.target.value)} /></label>
        <label>Max projects (empty = unlimited)<input inputMode="numeric" value={f.max_projects} onChange={(e) => set("max_projects", e.target.value)} /></label>
        <label>Max websites (empty = unlimited)<input inputMode="numeric" value={f.max_websites} onChange={(e) => set("max_websites", e.target.value)} /></label>
        <label>Paddle product id (pro_…)<input value={f.product} onChange={(e) => set("product", e.target.value)} /></label>
        <label>Paddle price id, with trial (pri_…)<input value={f.price} onChange={(e) => set("price", e.target.value)} /></label>
        <label>Paddle price id, without trial (pri_…)<input value={f.price_nt} onChange={(e) => set("price_nt", e.target.value)} /></label>
        <fieldset><legend>Features (default = not restricted by this plan)</legend>
          {Object.entries(data.features).map(([k, label]) => (
            <label key={k}>{label}
              <select value={features[k]} onChange={(e) => setFeatures((s) => ({ ...s, [k]: e.target.value as "default" | "on" | "off" }))}>
                <option value="default">Not restricted</option><option value="on">Included</option><option value="off">Switched off</option>
              </select>
            </label>
          ))}
        </fieldset>
        <fieldset><legend>Usage limits (empty = unlimited)</legend>
          {Object.entries(data.usage_limits).map(([k, label]) => <label key={k}>{label}<input inputMode="numeric" value={limits[k]} onChange={(e) => setLimits((s) => ({ ...s, [k]: e.target.value }))} /></label>)}
        </fieldset>
        <label className={styles.check}><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> Active</label>
        <label className={styles.check}><input type="checkbox" checked={f.is_public} onChange={(e) => set("is_public", e.target.checked)} /> Show on the public pricing page (once approved)</label>
        <label className={styles.check}><input type="checkbox" checked={f.is_test_config} onChange={(e) => set("is_test_config", e.target.checked)} /> Sandbox test configuration (cannot be sold in Live)</label>
        {plan && <label className={styles.check}><input type="checkbox" checked={f.is_approved} onChange={(e) => set("is_approved", e.target.checked)} /> Approved for real sales and public display</label>}
        <label>Reason (recorded in the audit log)<textarea rows={2} value={f.reason} onChange={(e) => set("reason", e.target.value)} /></label>
        <label className={styles.check}><input type="checkbox" checked={f.confirm} onChange={(e) => set("confirm", e.target.checked)} /> I confirm this change</label>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.dialogActions}>
          <button type="button" className={styles.secondary} onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className={styles.primary} disabled={busy || !f.reason.trim() || !f.confirm} onClick={submit}>{busy ? "Saving…" : "Save plan"}</button>
        </div>
      </div>
    </div>
  );
}

export function PlansSection() {
  const { data, loading, error, reload } = useAdminData<PlansData>("billing/plans");
  const [editing, setEditing] = useState<PlanRow | "new" | null>(null);
  return (
    <section aria-label="Plan catalogue">
      <DataState loading={loading && !data} error={error} onRetry={reload}>
        {data && (
          <>
            <p>
              Paddle environment: <Badge tone={data.paddle.environment === "live" ? "warn" : "neutral"}>{data.paddle.environment}</Badge>{" "}
              Provider: <Badge tone={data.paddle.provider_active ? "good" : "neutral"}>{data.paddle.provider_active ? "Paddle checkout active" : "Paddle not active"}</Badge>{" "}
              API key <Badge tone={data.paddle.api_key_set ? "good" : "bad"}>{data.paddle.api_key_set ? "set" : "missing"}</Badge>{" "}
              Client token <Badge tone={data.paddle.client_token_set ? "good" : "warn"}>{data.paddle.client_token_set ? "set" : "missing"}</Badge>{" "}
              Webhook secret <Badge tone={data.paddle.webhook_secret_set ? "good" : "bad"}>{data.paddle.webhook_secret_set ? "set" : "missing"}</Badge>
            </p>
            <p className={styles.muted}>Webhook destination to register in Paddle: <code>{data.paddle.webhook_url}</code></p>
            <p><button type="button" className={styles.primary} onClick={() => setEditing("new")}>New plan</button></p>
            <table className={styles.table}>
              <thead><tr><th>Plan</th><th>Interval</th><th>Price</th><th>Trial</th><th>Projects</th><th>Paddle price</th><th>State</th><th>Subscriptions</th><th /></tr></thead>
              <tbody>{data.items.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}<br /><span className={styles.muted}>{p.code}</span></td><td>{p.interval}</td>
                  <td>{p.amount_cents == null ? <Badge tone="warn">not decided</Badge> : formatMoney(p.amount_cents, p.currency)}</td>
                  <td>{p.trial_days || "—"}</td><td>{p.max_projects ?? "∞"}</td><td>{p.paddle_price_id ?? <Badge tone="warn">unmapped</Badge>}</td>
                  <td>
                    {p.is_approved ? <Badge tone="good">approved</Badge> : <Badge tone="neutral">unapproved</Badge>}{" "}
                    {p.is_test_config && <Badge tone="warn">sandbox test</Badge>}{" "}
                    {p.publicly_visible && <Badge tone="good">public</Badge>}{" "}{p.sellable && <Badge tone="good">sellable</Badge>}{!p.is_active && <Badge tone="neutral">inactive</Badge>}
                  </td>
                  <td>{p.subscriptions}</td><td><button type="button" className={styles.secondary} onClick={() => setEditing(p)}>Edit</button></td>
                </tr>
              ))}</tbody>
            </table>
            {data.items.length === 0 && <p className={styles.muted}>No plans yet. Nothing is on sale and the public site shows no prices.</p>}
            {editing && <PlanForm data={data} plan={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload(); }} />}
          </>
        )}
      </DataState>
    </section>
  );
}

interface CustomerRow { id: string; email: string | null; provider: string; provider_customer_id: string; environment: string; created_at: string }
export function BillingCustomersSection() {
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useAdminData<Paged<CustomerRow>>("billing/customers", { page });
  return (
    <section aria-label="Billing customers">
      <DataState loading={loading && !data} error={error} empty={data?.items.length === 0} onRetry={reload}>
        {data && (
          <>
            <table className={styles.table}>
              <thead><tr><th>Email</th><th>Provider</th><th>Customer id</th><th>Environment</th></tr></thead>
              <tbody>{data.items.map((c) => <tr key={c.id}><td>{c.email ?? "—"}</td><td>{c.provider}</td><td>{c.provider_customer_id}</td><td>{c.environment}</td></tr>)}</tbody>
            </table>
            <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </section>
  );
}
