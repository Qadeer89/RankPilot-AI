"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { OnboardingStatus, getOnboardingStatus } from "@/lib/api";
import styles from "./OnboardingChecklist.module.css";

/** Persistent setup checklist (Part 3: "accessible from the
 * dashboard"). Hidden entirely once onboarding is complete, and
 * dismissible per-session even before that so it doesn't nag a
 * returning user mid-task. */
export default function OnboardingChecklist({
  token,
  organizationId,
}: {
  token: string;
  organizationId: string;
}) {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    getOnboardingStatus(token, organizationId)
      .then(setStatus)
      .catch(() => {
        /* Non-critical widget -- a failed fetch just hides it. */
      });
  }, [token, organizationId]);

  if (!status || status.completed_at || dismissed) {
    return null;
  }

  const relevant = status.steps.filter((s) => s.mandatory || !s.skipped);
  const completedCount = status.steps.filter((s) => s.completed).length;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div>
          <h2>Finish setting up RankPilot</h2>
          <p className={styles.subtitle}>
            {completedCount} of {status.steps.length} steps complete
          </p>
        </div>
        <button type="button" className={styles.dismiss} onClick={() => setDismissed(true)}>
          Hide for now
        </button>
      </div>
      <ul className={styles.list}>
        {relevant.slice(0, 5).map((step) => (
          <li key={step.key} className={styles.item}>
            <span className={step.completed ? styles.dotDone : styles.dotPending} />
            <span className={step.completed ? styles.textDone : undefined}>{step.title}</span>
          </li>
        ))}
      </ul>
      <Link href="/dashboard/onboarding" className={styles.continueLink}>
        Continue setup
      </Link>
    </div>
  );
}
