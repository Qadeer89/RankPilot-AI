// Turns the raw strings and JSON the API stores on a growth recommendation
// into text a person can read. Pure functions, no I/O.

/** "Create blog_post for ..." -> "Create blog post for ..." (also fixes
 * recommendations saved before the API started writing readable text). */
export function readable(text: string): string {
  return text.replace(/\b([a-z]+)_([a-z]+(?:_[a-z]+)*)\b/g, (m) => m.replaceAll("_", " "));
}

const DATA_CLASSIFICATION: Record<string, string> = {
  ai_generated_idea: "AI-generated idea (not verified demand)",
  verified_first_party: "from your own site data",
  verified_external_source: "from a verified external source",
};

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A short, human summary of `evidence_json`. Internal ids are never shown. */
export function describeEvidence(evidence: Record<string, unknown>): string {
  const parts: string[] = [];
  const impressions = num(evidence.impressions);
  const position = num(evidence.average_position);
  const confidence = num(evidence.confidence);
  const windowDays = num(evidence.window_days);

  if (impressions !== null) parts.push(`${impressions} impressions`);
  if (position !== null) parts.push(`average position ${position}`);
  if (confidence !== null) parts.push(`AI confidence ${Math.round(confidence * 100)}%`);
  if (typeof evidence.data_classification === "string") {
    parts.push(DATA_CLASSIFICATION[evidence.data_classification] ?? evidence.data_classification.replaceAll("_", " "));
  }
  if (typeof evidence.competitor_domain === "string") parts.push(`competitor: ${evidence.competitor_domain}`);
  if (Array.isArray(evidence.pages)) parts.push(`${evidence.pages.length} pages compete for this query`);
  if (Array.isArray(evidence.signals)) parts.push(`signals: ${evidence.signals.map((s) => String(s).replaceAll("_", " ")).join(", ")}`);

  const prior = evidence.prior as Record<string, unknown> | undefined;
  const recent = evidence.recent as Record<string, unknown> | undefined;
  if (prior && recent && num(prior.clicks) !== null && num(recent.clicks) !== null) {
    parts.push(`clicks ${prior.clicks} → ${recent.clicks}`);
  }
  if (prior && recent && num(prior.impressions) !== null && num(recent.impressions) !== null) {
    parts.push(`impressions ${prior.impressions} → ${recent.impressions}`);
  }
  if (windowDays !== null && (impressions !== null || prior)) parts.push(`last ${windowDays} days`);

  return parts.length ? parts.join(" · ") : "no extra evidence recorded";
}
