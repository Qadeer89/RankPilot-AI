"use client";

import { useState } from "react";
import { ApiError, TitleRepairPlan, createTitleRepairTasks, planTitleRepair } from "@/lib/api";
import styles from "./TitleRepairCard.module.css";

const BATCH = 10;

export function TitleRepairCard({ getAuth, websiteId, onCreated }: { getAuth: () => { token: string | null; orgId: string | null }; websiteId: string; onCreated: () => void | Promise<void> }) {
  const [plan, setPlan] = useState<TitleRepairPlan | null>(null);
  const [busy, setBusy] = useState<"plan" | "create" | "loading" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

  async function check() {
    const { token, orgId } = getAuth();
    if (!token || !orgId) return;
    setBusy("plan"); setError(null); setDone(null);
    try { setPlan(await planTitleRepair(token, orgId, websiteId, BATCH)); } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  }
  async function create() {
    const { token, orgId } = getAuth();
    if (!token || !orgId) return;
    setBusy("create"); setError(null);
    try {
      const r = await createTitleRepairTasks(token, orgId, websiteId, BATCH);
      setDone(r.message); setPlan(r.plan);
      setBusy("loading"); // the new tasks are being loaded into the list below
      await onCreated();
    } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  }

  return (
    <section className={styles.card} aria-label="Fix doubled brand in titles">
      <h3>Fix titles that show your brand twice</h3>
      <p className={styles.small}>
        Some titles RankPilot changed earlier now show the brand twice (for example &ldquo;Page | Brand | Brand&rdquo;) because your site adds the brand itself.
        This checks the live pages, shows what each title would become, and creates tasks that wait for your approval. Nothing changes on your website until you approve and run each task below.
      </p>
      <div className={styles.row}>
        <button type="button" className={styles.btn} onClick={check} disabled={busy !== null}>{busy === "plan" ? "Checking pages…" : "Check pages (read-only)"}</button>
        {plan && plan.candidates.length > 0 && !done && (
          <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={create} disabled={busy !== null}>
            {busy === "create" ? "Creating…" : `Create ${plan.candidates.length} approval task(s)`}
          </button>
        )}
      </div>
      {busy === "plan" && (
        <p className={styles.busy} role="status" data-testid="repair-busy"><span className={styles.spinner} aria-hidden="true" />Checking the live pages one by one. This can take up to 40 seconds, please keep this page open.</p>
      )}
      {busy === "create" && (
        <p className={styles.busy} role="status" data-testid="repair-busy"><span className={styles.spinner} aria-hidden="true" />Creating the tasks. This re-checks each live page, so it can take up to 40 seconds. Please keep this page open; the new tasks will appear in the list below.</p>
      )}
      {busy === "loading" && (
        <p className={styles.busy} role="status" data-testid="repair-busy"><span className={styles.spinner} aria-hidden="true" />Tasks created. Loading them into the list below…</p>
      )}
      {error && <p className={styles.error} role="alert">{error}</p>}
      {done && <p className={styles.ok} role="status" data-testid="repair-done">{done}</p>}
      {plan && (
        <div data-testid="repair-plan">
          {plan.reason_none && <p className={styles.small}>{plan.reason_none}</p>}
          {plan.candidates.length === 0 && !plan.reason_none && <p className={styles.small}>No pages need this fix right now{plan.skipped_already_pending ? ` (${plan.skipped_already_pending} already have a task waiting)` : ""}.</p>}
          {plan.stopped_early && <p className={styles.warn}>Checking took too long, so this list is only part of the pages. Run it again to continue.</p>}
          {done && plan.candidates.length > 0 && <p className={styles.small} data-testid="repair-created-for"><strong>Tasks were created for these pages.</strong> Find them in the task list below (status: waiting for approval), then Approve and Execute one at a time.</p>}
          <ul className={styles.list}>
            {plan.candidates.map((c) => (
              <li key={c.url}>
                <strong>{c.url}</strong>
                <span className={styles.small}>Live now: {c.live_title}</span>
                <span>New title: {c.new_title}</span>
                {c.final_title && (
                  <span className={c.too_long ? styles.warnText : styles.small}>
                    In search results: {c.final_title} ({c.final_length} characters{c.too_long ? " — may be cut off; shorten it in a later round" : ""})
                  </span>
                )}
              </li>
            ))}
          </ul>
          {plan.candidates.length > 0 && !done && <p className={styles.small}>Showing the next {plan.candidates.length} page(s) of {plan.pages_with_applied_titles} that RankPilot changed. After these are done, check again for the next batch.</p>}
        </div>
      )}
    </section>
  );
}
