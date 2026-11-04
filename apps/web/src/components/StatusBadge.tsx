import styles from "./StatusBadge.module.css";

type Tone = "good" | "bad" | "warn" | "info" | "neutral";

// Every value here is a real backend enum value (website/task/crawl
// status, verification_status, finding severity, approval_status, ...).
// Never invent a label or a tier the backend doesn't actually have --
// RankPilot AI UI/UX Redesign Prompt Pack v1.0 #7 rules 2 and 3.
const GOOD = new Set([
  "verified",
  "passed",
  "completed",
  "resolved",
  "indexable",
  "sent",
  "approved",
  "connected",
  "active",
]);
const BAD = new Set(["failed", "unverified", "rejected", "error", "disconnected", "critical"]);
const WARN = new Set(["pending", "executing", "running", "skipped_not_configured", "noindex", "paused", "warning"]);
const INFO = new Set(["info", "not_required"]);

function inferTone(value: string): Tone {
  const v = value.toLowerCase();
  if (GOOD.has(v)) return "good";
  if (BAD.has(v)) return "bad";
  if (WARN.has(v)) return "warn";
  if (INFO.has(v)) return "info";
  return "neutral";
}

export default function StatusBadge({
  value,
  tone,
  label,
}: {
  value: string;
  tone?: Tone;
  label?: string;
}) {
  const resolvedTone = tone ?? inferTone(value);
  const className = [styles.badge, resolvedTone !== "neutral" ? styles[resolvedTone] : ""]
    .filter(Boolean)
    .join(" ");
  return <span className={className}>{label ?? value}</span>;
}
