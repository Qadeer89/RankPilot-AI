"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  DryRunResult,
  GrowthRecommendation,
  LifecycleTask,
  approveTask,
  createProposal,
  createTasks,
  dryRunTask,
  executeTask,
  recrawlGrowthRecommendation,
  rejectTask,
  rollbackChange,
  sendGrowthRecommendationToExecution,
  verifyGrowthRecommendationLive,
} from "@/lib/api";
import styles from "@/app/dashboard/websites/[id]/keywords/keywords.module.css";

interface Props {
  token: string;
  organizationId: string;
  websiteId: string;
  rec: GrowthRecommendation;
  onChanged: () => Promise<void> | void;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending", approved: "Approved", rejected: "Rejected", in_progress: "In progress",
  applied: "Applied (manually)", validation_pending: "Validation pending", validated: "Validated",
  failed: "Failed", rolled_back: "Rolled back",
};

export default function RecommendationExecution({ token, organizationId, websiteId, rec, onChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previews, setPreviews] = useState<Record<string, DryRunResult>>({});
  const life = rec.lifecycle ?? {};
  const status = life.lifecycle_status ?? "pending";
  const tasks = life.tasks ?? [];
  const crawling = tasks.some((t) => t.recrawl && (t.recrawl.status === "queued" || t.recrawl.status === "running"));

  // While the verification crawl is queued or running, check back every few
  // seconds so the result appears without a manual refresh (bounded, so a
  // stuck worker does not poll forever).
  const onChangedRef = useRef(onChanged);
  useEffect(() => {
    onChangedRef.current = onChanged;
  });
  useEffect(() => {
    if (!crawling) return;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (attempts > 40) {
        clearInterval(timer);
        return;
      }
      void onChangedRef.current();
    }, 5000);
    return () => clearInterval(timer);
  }, [crawling]);

  async function run(key: string, action: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That step did not complete.");
    } finally {
      setBusy(null);
    }
  }

  async function prepareDraft() {
    const updated = await sendGrowthRecommendationToExecution(token, organizationId, websiteId, rec.id);
    if (!updated.opportunity_id) throw new ApiError(409, "No change could be prepared.");
    const proposal = await createProposal(token, organizationId, websiteId, updated.opportunity_id);
    await createTasks(token, organizationId, websiteId, updated.opportunity_id, proposal);
  }

  return (
    <div className={styles.execPanel} aria-label="Execution status">
      <div className={styles.cardHeader}>
        <strong>Execution</strong>
        <span className={styles.badge}>{STATUS_LABEL[status] ?? status}</span>
      </div>

      {life.supported === false && (
        <p className={styles.freshnessNote} data-testid="unsupported-reason">
          Cannot be applied automatically: {life.unsupported_reason}
        </p>
      )}

      {life.supported && rec.status === "approved" && tasks.length === 0 && (
        <button type="button" className={styles.primaryButton} disabled={busy !== null}
          onClick={() => run("prepare", prepareDraft)}>
          {busy === "prepare" ? "Preparing…" : "Prepare AI draft change"}
        </button>
      )}
      {life.supported && rec.status === "open" && (
        <p className={styles.freshnessNote}>Approve this recommendation first to prepare a change.</p>
      )}

      {tasks.map((task) => {
        const preview = previews[task.task_id];
        return (
          <div key={task.task_id} className={styles.recCard}>
            <p>
              <strong>{task.operation.replaceAll("_", " ")}</strong> on {task.target_url ?? "the page"} — {STATE_TEXT(task.state)}
            </p>
            <p>
              <strong>Recommended:</strong> {task.proposed_value}
              {task.summary ? <><br /><span className={styles.subtitle}>{task.summary}</span></> : null}
            </p>
            {(preview || task.before_value != null) && (
              <table className={styles.table}>
                <thead><tr><th>Before</th><th>After</th></tr></thead>
                <tbody>
                  <tr>
                    <td>{preview ? preview.before_value : task.before_value}</td>
                    <td>{preview ? preview.proposed_value : task.applied_value}</td>
                  </tr>
                </tbody>
              </table>
            )}
            {task.recrawl && <p className={styles.freshnessNote} data-testid="recrawl-status">{recrawlText(task.recrawl)}</p>}
            <div className={styles.domainActions}>
              {task.state === "in_progress" && task.approval_status === "pending" && (
                <>
                  <button type="button" className={styles.secondaryButton} disabled={busy !== null}
                    onClick={() => run(`p${task.task_id}`, async () => {
                      const result = await dryRunTask(token, organizationId, websiteId, task.task_id);
                      setPreviews((prev) => ({ ...prev, [task.task_id]: result }));
                    })}>Preview before / after</button>
                  <button type="button" className={styles.primaryButton} disabled={busy !== null}
                    onClick={() => run(`a${task.task_id}`, () => approveTask(token, organizationId, websiteId, task.task_id))}>
                    Approve change
                  </button>
                  <button type="button" className={styles.secondaryButton} disabled={busy !== null}
                    onClick={() => run(`r${task.task_id}`, () => rejectTask(token, organizationId, websiteId, task.task_id))}>
                    Reject change
                  </button>
                </>
              )}
              {task.state === "in_progress" && task.approval_status === "approved" && (
                <button type="button" className={styles.primaryButton} disabled={busy !== null}
                  onClick={() => run(`x${task.task_id}`, () => executeTask(token, organizationId, websiteId, task.task_id))}>
                  {busy === `x${task.task_id}` ? "Applying…" : "Apply to site"}
                </button>
              )}
              {task.change_record_id && task.state !== "rolled_back" && (
                <button type="button" className={styles.secondaryButton} disabled={busy !== null}
                  onClick={() => run(`b${task.task_id}`, () => rollbackChange(token, organizationId, websiteId, task.change_record_id as string))}>
                  Roll back
                </button>
              )}
            </div>
          </div>
        );
      })}

      {tasks.some((t) => t.change_record_id) && (
        <div className={styles.domainActions}>
          <button type="button" className={styles.secondaryButton} disabled={busy !== null || crawling}
            onClick={() => run("recrawl", () => recrawlGrowthRecommendation(token, organizationId, websiteId, rec.id))}>
            {crawling ? "Re-crawl running…" : "Re-crawl page"}
          </button>
          <button type="button" className={styles.secondaryButton} disabled={busy !== null}
            onClick={() => run("live", () => verifyGrowthRecommendationLive(token, organizationId, websiteId, rec.id))}>
            {busy === "live" ? "Checking…" : "Check the live page"}
          </button>
        </div>
      )}
      {life.live_check && (
        <p className={styles.freshnessNote}>
          Live check {new Date(life.live_check.checked_at).toLocaleString()}:{" "}
          {life.live_check.matched ? "the public page shows the new value." : "the public page does not show the new value yet (caching or a pending deploy can cause this)."}
        </p>
      )}
      {error && <p className={styles.error} role="alert">{error}</p>}
    </div>
  );
}

function STATE_TEXT(state: string): string {
  return STATUS_LABEL[state] ?? state;
}

function recrawlText(r: NonNullable<LifecycleTask["recrawl"]>): string {
  switch (r.status) {
    case "queued":
      return "Re-crawl queued: RankPilot will fetch the page and confirm the change is visible.";
    case "running":
      return "Re-crawl running…";
    case "validated":
      return "Re-crawl confirmed: the crawled page shows the new value.";
    case "mismatch":
      return `Re-crawl did not see the change yet (found "${r.found ?? "nothing"}"). A cache or a pending deploy can cause this. Try "Re-crawl page" again shortly.`;
    case "failed":
      return `Re-crawl could not verify the change: ${r.error ?? "the page could not be crawled."}`;
    case "not_applicable":
      return "Re-crawl finished. This kind of change is not visible in a crawl snapshot, so it was not compared.";
    default:
      return `Re-crawl was not started: ${r.error ?? "unknown reason."}`;
  }
}
