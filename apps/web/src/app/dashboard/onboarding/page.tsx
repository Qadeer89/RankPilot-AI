"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  MeResponse,
  OnboardingStatus,
  completeOnboarding,
  dismissOnboardingWelcome,
  getMe,
  getOnboardingStatus,
  skipOnboardingStep,
  unskipOnboardingStep,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { STEP_CONTENT } from "./step-content";
import styles from "./onboarding.module.css";

export default function OnboardingPage() {
  const router = useRouter();
  const tokenRef = useRef<string | null>(null);
  const orgIdRef = useRef<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (token: string, orgId: string) => {
    const result = await getOnboardingStatus(token, orgId);
    setStatus(result);
    return result;
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    tokenRef.current = token;
    getMe(token)
      .then(async (meResponse) => {
        setMe(meResponse);
        const org = meResponse.organizations[0];
        if (!org) return;
        orgIdRef.current = org.id;
        await refresh(token, org.id);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load onboarding status.");
      });
  }, [router, refresh]);

  if (!me || !status) {
    return (
      <div className={styles.page}>
        {error ? <p className={styles.error} role="alert">{error}</p> : <p>Loading...</p>}
      </div>
    );
  }

  const steps = status.steps;
  const activeStep = steps[activeIndex];
  const content = STEP_CONTENT[activeStep.key];
  const completedCount = steps.filter((s) => s.completed).length;
  const progressPct = Math.round((completedCount / steps.length) * 100);

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSkip() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    await withBusy(async () => {
      await skipOnboardingStep(token, orgId, activeStep.key);
      await refresh(token, orgId);
    });
  }

  async function handleUnskip() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    await withBusy(async () => {
      await unskipOnboardingStep(token, orgId, activeStep.key);
      await refresh(token, orgId);
    });
  }

  async function handleDismissWelcome() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    await withBusy(async () => {
      await dismissOnboardingWelcome(token, orgId);
      await refresh(token, orgId);
    });
  }

  async function handleFinish() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    await withBusy(async () => {
      const result = await completeOnboarding(token, orgId);
      setStatus(result);
      if (result.completed_at) {
        router.push("/dashboard");
        return;
      }
      const firstIncomplete = result.steps.findIndex((s) => s.mandatory && !s.completed);
      if (firstIncomplete !== -1) {
        setActiveIndex(firstIncomplete);
        setError(`"${result.steps[firstIncomplete].title}" still isn't complete -- see below.`);
      }
    });
  }

  function handlePrimaryActionClick() {
    if (activeStep.key === "welcome" && !activeStep.completed) {
      // Starting setup is itself an acknowledgement of the welcome
      // screen -- don't make the user come back and press "Got it"
      // separately, or they can reach the end of the wizard with
      // "welcome" silently still incomplete and Finish never firing.
      handleDismissWelcome();
    }
  }

  const isLast = activeIndex === steps.length - 1;
  const isFirst = activeIndex === 0;

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1>Guided setup</h1>
          <Link href="/dashboard" className={styles.exitLink}>
            Exit to dashboard
          </Link>
        </div>

        <div className={styles.progressTrack}>
          <div className={styles.progressFill} style={{ width: `${progressPct}%` }} />
        </div>
        <p className={styles.progressLabel}>
          {completedCount} of {steps.length} steps complete
        </p>

        {error && <p className={styles.error} role="alert">{error}</p>}

        <div className={styles.body}>
          <nav className={styles.checklist} aria-label="Setup steps">
            {steps.map((step, index) => (
              <button
                key={step.key}
                type="button"
                className={`${styles.checklistItem} ${index === activeIndex ? styles.checklistItemActive : ""}`}
                onClick={() => setActiveIndex(index)}
              >
                <span
                  className={
                    step.completed
                      ? styles.dotCompleted
                      : step.skipped
                        ? styles.dotSkipped
                        : styles.dotPending
                  }
                />
                <span>{step.title}</span>
                {!step.mandatory && <span className={styles.optionalTag}>optional</span>}
              </button>
            ))}
          </nav>

          <section className={styles.content}>
            <h2>{content.heading}</h2>
            {content.body.map((paragraph, i) => (
              <p key={i}>{paragraph}</p>
            ))}
            <p className={styles.statusLine}>
              Status:{" "}
              {activeStep.completed ? "Completed" : activeStep.skipped ? "Skipped" : "Not completed yet"} --{" "}
              {activeStep.detail}
            </p>

            <div className={styles.actions}>
              <Link href={content.actionHref} className={styles.primaryAction} onClick={handlePrimaryActionClick}>
                {content.actionLabel}
              </Link>
              {!activeStep.mandatory && !activeStep.skipped && (
                <button type="button" className={styles.secondaryAction} onClick={handleSkip} disabled={busy}>
                  Skip this step
                </button>
              )}
              {!activeStep.mandatory && activeStep.skipped && (
                <button type="button" className={styles.secondaryAction} onClick={handleUnskip} disabled={busy}>
                  Undo skip
                </button>
              )}
              {activeStep.key === "welcome" && !activeStep.completed && (
                <button type="button" className={styles.secondaryAction} onClick={handleDismissWelcome} disabled={busy}>
                  Got it, mark as read
                </button>
              )}
            </div>

            <div className={styles.navRow}>
              <button
                type="button"
                className={styles.navButton}
                onClick={() => setActiveIndex((i) => Math.max(0, i - 1))}
                disabled={isFirst}
              >
                Previous
              </button>
              {!isLast ? (
                <button
                  type="button"
                  className={styles.navButton}
                  onClick={() => setActiveIndex((i) => Math.min(steps.length - 1, i + 1))}
                >
                  Next
                </button>
              ) : (
                <button type="button" className={styles.primaryAction} onClick={handleFinish} disabled={busy}>
                  {status.all_mandatory_complete ? "Finish setup" : "Review and finish"}
                </button>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
