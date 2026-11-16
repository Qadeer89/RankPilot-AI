"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  BillingOverview,
  BillingPlan,
  BillingProject,
  ReplacementTargets,
  getBillingOverview,
  getMe,
  getReplacementTargets,
  replaceSubscriptionProject,
  startCheckout,
} from "@/lib/api";
import { formatDate, formatMoney, planLabel, priceLine, STATUS_LABEL, statusTone } from "@/lib/billingFormat";
import { getToken } from "@/lib/auth";
import styles from "./billing.module.css";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 20;

function toneClass(tone: "good" | "warn" | "bad" | "neutral"): string {
  if (tone === "good") return `${styles.badge} ${styles.badgeGood}`;
  if (tone === "warn") return `${styles.badge} ${styles.badgeWarn}`;
  if (tone === "bad") return `${styles.badge} ${styles.badgeBad}`;
  return styles.badge;
}

function PlanPicker({
  project,
  plans,
  saving,
  onStart,
  busy,
}: {
  project: BillingProject;
  plans: BillingPlan[];
  saving: number;
  onStart: (interval: "month" | "year") => void;
  busy: boolean;
}) {
  const [interval, setInterval] = useState<"month" | "year">("year");
  const [openedAt] = useState(() => Date.now());
  const plan = plans.find((p) => p.interval === interval) ?? plans[0];
  const trial = project.trial_available;
  const firstCharge = trial ? new Date(openedAt + plan.trial_days * 86400000).toISOString() : null;
  return (
    <div aria-label={`Choose a plan for ${project.display_name}`}>
      <div className={styles.plans} role="radiogroup" aria-label="Billing plan">
        {plans.map((p) => (
          <button
            key={p.interval}
            type="button"
            role="radio"
            aria-checked={interval === p.interval}
            className={`${styles.plan} ${interval === p.interval ? styles.planSelected : ""}`}
            onClick={() => setInterval(p.interval)}
          >
            <span className={styles.planName}>{planLabel(p.interval)}</span>
            <span className={styles.planPrice}>{priceLine(p.price_cents, p.currency, p.interval)}</span>
            <span className={styles.planNote}>
              {p.interval === "year"
                ? `${formatMoney(p.monthly_equivalent_cents, p.currency)} a month. Save ${formatMoney(saving, p.currency)} a year: 2 months free.`
                : "Billed every month."}
            </span>
          </button>
        ))}
      </div>
      <p className={styles.summary} data-testid="checkout-summary">
        {trial ? (
          <>
            <strong>{plan.trial_days}-day free trial</strong>, then {priceLine(plan.price_cents, plan.currency, plan.interval)} for this
            project. A payment method is collected at checkout; the first charge is on about {formatDate(firstCharge)}. Cancel any time
            from this page before then and you will not be charged.
          </>
        ) : (
          <>
            This project already used its free trial, so billing starts now at {priceLine(plan.price_cents, plan.currency, plan.interval)}.
            Cancel any time; access continues to the end of the paid period.
          </>
        )}{" "}
        Includes every target country for this project.
      </p>
      <div className={styles.actions} style={{ marginTop: 12 }}>
        <button type="button" className={`${styles.button} ${styles.buttonPrimary}`} disabled={busy} onClick={() => onStart(interval)}>
          {busy ? "Opening checkout…" : trial ? "Start free trial" : `Subscribe ${planLabel(interval).toLowerCase()}`}
        </button>
      </div>
    </div>
  );
}

function ReplaceDialog({
  project,
  targets,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  project: BillingProject;
  targets: ReplacementTargets | null;
  busy: boolean;
  error: string | null;
  onConfirm: (targetId: string) => void;
  onCancel: () => void;
}) {
  const [targetId, setTargetId] = useState("");
  const [understand, setUnderstand] = useState(false);
  const [confirmMove, setConfirmMove] = useState(false);
  const target = targets?.targets.find((t) => t.id === targetId);
  const ready = Boolean(targetId) && understand && confirmMove && !busy;
  return (
    <div className={styles.scrim} onClick={onCancel}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="Replace project" onClick={(e) => e.stopPropagation()}>
        <h3>Move this subscription to another project</h3>
        <p className={styles.meta}>
          The subscription for <strong>{project.display_name}</strong> keeps its plan, price, renewal date, trial and payment history.
          Only the project it covers changes. <strong>This can be done once per subscription and cannot be undone.</strong>
        </p>
        {!targets ? (
          <p className={styles.empty}>Loading projects…</p>
        ) : targets.targets.length === 0 ? (
          <p className={styles.empty}>There is no other project in this workspace without its own subscription. Add one first.</p>
        ) : (
          <>
            <label className={styles.factLabel} htmlFor="replace-target">New project</label>
            <select id="replace-target" className={styles.select} value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">Choose a project…</option>
              {targets.targets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.display_name} ({t.hostname})
                </option>
              ))}
            </select>
            <label className={styles.check}>
              <input type="checkbox" checked={understand} onChange={(e) => setUnderstand(e.target.checked)} />
              <span>I understand this replacement is permanent and can only be used once for this subscription.</span>
            </label>
            <label className={styles.check}>
              <input type="checkbox" checked={confirmMove} onChange={(e) => setConfirmMove(e.target.checked)} />
              <span>
                Move the subscription from <strong>{project.display_name}</strong> to <strong>{target ? target.display_name : "the selected project"}</strong>.
                {project.display_name} will lose paid features.
              </span>
            </label>
          </>
        )}
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.actions}>
          <button type="button" className={styles.button} onClick={onCancel}>Cancel</button>
          <button type="button" className={`${styles.button} ${styles.buttonPrimary}`} disabled={!ready} onClick={() => onConfirm(targetId)}>
            {busy ? "Moving…" : "Replace project"}
          </button>
        </div>
      </div>
    </div>
  );
}

function BillingContent() {
  const router = useRouter();
  const params = useSearchParams();
  const returned = params.get("checkout") === "return";
  const returnedProject = params.get("project");
  const tokenRef = useRef<string | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyProject, setBusyProject] = useState<string | null>(null);
  const [replacing, setReplacing] = useState<BillingProject | null>(null);
  const [targets, setTargets] = useState<ReplacementTargets | null>(null);
  const [replaceError, setReplaceError] = useState<string | null>(null);
  const [replaceBusy, setReplaceBusy] = useState(false);

  const load = useCallback(async () => {
    const token = tokenRef.current;
    if (!token || !orgId) return;
    try {
      setOverview(await getBillingOverview(token, orgId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load billing.");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    tokenRef.current = token;
    getMe(token)
      .then((me) => {
        const id = me.organizations[0]?.id;
        if (!id) {
          setLoading(false);
          return;
        }
        setOrgId(id);
      })
      .catch(() => router.push("/login"));
  }, [router]);

  useEffect(() => {
    if (!orgId) return;
    void load();
  }, [orgId, load]);

  // After returning from the payment page the subscription only appears once the provider's
  // verified webhook has been processed, so keep checking for a little while.
  const subscribed = overview?.projects.find((p) => p.website_id === returnedProject)?.subscription != null;
  const [gaveUp, setGaveUp] = useState(false);
  const confirming = returned && !subscribed && !gaveUp;
  useEffect(() => {
    if (!confirming) return;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (attempts > POLL_MAX_ATTEMPTS) {
        clearInterval(timer);
        setGaveUp(true);
        return;
      }
      void load();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [confirming, load]);

  async function handleStart(project: BillingProject, interval: "month" | "year") {
    const token = tokenRef.current;
    if (!token || !orgId) return;
    setBusyProject(project.website_id);
    setError(null);
    try {
      const started = await startCheckout(token, orgId, project.website_id, interval);
      window.location.assign(started.checkout_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start checkout.");
      setBusyProject(null);
    }
  }

  async function openReplace(project: BillingProject) {
    const token = tokenRef.current;
    if (!token || !orgId || !project.subscription) return;
    setReplacing(project);
    setTargets(null);
    setReplaceError(null);
    try {
      setTargets(await getReplacementTargets(token, orgId, project.subscription.id));
    } catch (err) {
      setReplaceError(err instanceof ApiError ? err.message : "Could not load projects.");
    }
  }

  async function confirmReplace(targetId: string) {
    const token = tokenRef.current;
    if (!token || !orgId || !replacing?.subscription) return;
    setReplaceBusy(true);
    setReplaceError(null);
    try {
      await replaceSubscriptionProject(token, orgId, replacing.subscription.id, targetId);
      setReplacing(null);
      setNotice("The subscription now covers the new project. The one-time replacement has been used.");
      await load();
    } catch (err) {
      setReplaceError(err instanceof ApiError ? err.message : "Could not replace the project.");
    } finally {
      setReplaceBusy(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1>Billing</h1>
          <p className={styles.subtitle}>One subscription covers one project, including all of its target countries.</p>
        </div>

        {overview?.enforcement === "off" && (
          <p className={styles.notice}>
            Billing is not enforced yet: your projects keep full access while plans are being rolled out.
          </p>
        )}
        {confirming && <p className={styles.notice} role="status">Confirming your payment with the payment provider…</p>}
        {returned && subscribed && <p className={styles.success} role="status">Your subscription is confirmed.</p>}
        {returned && gaveUp && !subscribed && (
          <p className={styles.notice} role="status">
            We have not received the payment confirmation yet. It can take a few minutes; refresh this page shortly.
          </p>
        )}
        {notice && <p className={styles.success} role="status">{notice}</p>}
        {error && <p className={styles.error} role="alert">{error}</p>}
        {loading && <p className={styles.empty}>Loading billing…</p>}
        {!loading && overview && overview.projects.length === 0 && <p className={styles.empty}>Add a project first, then choose a plan for it.</p>}

        {overview?.projects.map((project) => {
          const sub = project.subscription;
          const tone = statusTone(sub?.status, project.entitlement.entitled);
          return (
            <section key={project.website_id} className={styles.card} aria-label={`Billing for ${project.display_name}`}>
              <div className={styles.cardHeader}>
                <div>
                  <h2>{project.display_name}</h2>
                  <p className={styles.meta}>
                    {project.hostname}
                    {project.target_countries.length > 0 ? ` · Targets: ${project.target_countries.join(", ")}` : ""}
                  </p>
                </div>
                <span className={toneClass(sub ? tone : "neutral")}>{sub ? STATUS_LABEL[sub.status] ?? sub.status : "No plan"}</span>
              </div>
              <p className={styles.meta}>{project.entitlement.message}</p>

              {sub ? (
                <>
                  <div className={styles.facts}>
                    <div className={styles.fact}>
                      <span className={styles.factLabel}>Plan</span>
                      <span className={styles.factValue}>
                        {sub.complimentary ? "Complimentary" : `${planLabel(sub.interval)} · ${priceLine(sub.price_cents, sub.currency, sub.interval)}`}
                      </span>
                    </div>
                    {sub.status === "trialing" && (
                      <div className={styles.fact}>
                        <span className={styles.factLabel}>Trial ends</span>
                        <span className={styles.factValue}>{formatDate(sub.trial_ends_at)}</span>
                      </div>
                    )}
                    {sub.cancellation_scheduled ? (
                      <div className={styles.fact}>
                        <span className={styles.factLabel}>Cancelled, access until</span>
                        <span className={styles.factValue}>{formatDate(sub.ends_at)}</span>
                      </div>
                    ) : sub.renews_at && !sub.complimentary ? (
                      <div className={styles.fact}>
                        <span className={styles.factLabel}>{sub.status === "trialing" ? "First charge" : "Next billing"}</span>
                        <span className={styles.factValue}>
                          {formatDate(sub.renews_at)} · {formatMoney(sub.price_cents, sub.currency)}
                        </span>
                      </div>
                    ) : null}
                    <div className={styles.fact}>
                      <span className={styles.factLabel}>Project replacement</span>
                      <span className={styles.factValue}>
                        {sub.replacements_remaining > 0 ? `${sub.replacements_remaining} left (one-time)` : "Used"}
                      </span>
                    </div>
                  </div>
                  <div className={styles.actions}>
                    {sub.customer_portal_url && (
                      <a className={styles.button} href={sub.customer_portal_url} target="_blank" rel="noreferrer">
                        Manage billing
                      </a>
                    )}
                    {sub.update_payment_url && ["past_due", "unpaid"].includes(sub.status) && (
                      <a className={`${styles.button} ${styles.buttonPrimary}`} href={sub.update_payment_url} target="_blank" rel="noreferrer">
                        Update payment method
                      </a>
                    )}
                    {sub.replacements_remaining > 0 && (
                      <button type="button" className={styles.button} onClick={() => openReplace(project)}>
                        Replace project
                      </button>
                    )}
                  </div>
                  {project.payments.length > 0 && (
                    <table className={styles.table} aria-label={`Payments for ${project.display_name}`}>
                      <thead>
                        <tr><th>Date</th><th>Amount</th><th>Status</th></tr>
                      </thead>
                      <tbody>
                        {project.payments.map((p) => (
                          <tr key={p.id}>
                            <td>{formatDate(p.paid_at ?? p.created_at)}</td>
                            <td>{formatMoney(p.amount_cents, p.currency)}{p.refunded_cents > 0 ? ` (refunded ${formatMoney(p.refunded_cents, p.currency)})` : ""}</td>
                            <td>{p.status.replace("_", " ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              ) : (
                <PlanPicker
                  project={project}
                  plans={overview.plans}
                  saving={overview.annual_saving_cents}
                  busy={busyProject === project.website_id}
                  onStart={(interval) => handleStart(project, interval)}
                />
              )}
            </section>
          );
        })}
      </div>

      {replacing && (
        <ReplaceDialog
          project={replacing}
          targets={targets}
          busy={replaceBusy}
          error={replaceError}
          onConfirm={confirmReplace}
          onCancel={() => setReplacing(null)}
        />
      )}
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense fallback={null}>
      <BillingContent />
    </Suspense>
  );
}
