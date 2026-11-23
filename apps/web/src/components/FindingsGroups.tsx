"use client";

import { useMemo, useState } from "react";
import type { SEOFinding } from "@/lib/api";
import { ruleHelp, ruleLabel } from "@/lib/ruleLabels";
import StatusBadge from "@/components/StatusBadge";
import styles from "./FindingsGroups.module.css";

const PAGE_SIZE = 15;
const SEVERITY_ORDER: Record<string, number> = { critical: 0, error: 1, warning: 2, info: 3 };

type Evidence = Record<string, unknown>;

/** Human-readable lines for what the crawler saw; unknown shapes fall back to key: value so nothing is hidden. */
export function describeEvidence(code: string, evidence: Evidence): string[] {
  const e = evidence ?? {};
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  if ((code === "EXTERNAL_LINK_REDIRECT" || code === "EXTERNAL_LINK_BROKEN") && Array.isArray(e.urls)) {
    return [`${num(e.count) ?? e.urls.length} link(s):`, ...(e.urls as unknown[]).map(String)];
  }
  if (code === "TITLE_TOO_LONG" && num(e.length) !== null) return [`The title is ${e.length} characters; search results show about ${e.threshold}.`];
  if (code === "THIN_CONTENT" && num(e.word_count) !== null) return [`${e.word_count} words (usual minimum ${e.threshold}) for a ${String(e.page_type ?? "page")} page.`];
  if (code === "HEADING_HIERARCHY_SKIP" && Array.isArray(e.sequence)) {
    return [`Heading order on the page: ${(e.sequence as unknown[]).map((n) => `H${n}`).join(" → ")}`];
  }
  const lines = Object.entries(e).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "string" ? v : JSON.stringify(v)}`);
  return lines.length ? lines : ["No further detail was recorded."];
}

/** A URL that appears in at least half of a rule's findings (and at least 5) is almost certainly one shared element. */
export function sharedUrls(code: string, items: SEOFinding[]): { url: string; pages: number }[] {
  if (code !== "EXTERNAL_LINK_REDIRECT" && code !== "EXTERNAL_LINK_BROKEN") return [];
  const counts = new Map<string, number>();
  for (const f of items) {
    const urls = Array.isArray((f.evidence_json as Evidence)?.urls) ? ((f.evidence_json as Evidence).urls as unknown[]).map(String) : [];
    for (const u of new Set(urls)) counts.set(u, (counts.get(u) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, n]) => n >= 5 && n >= items.length / 2)
    .map(([url, pages]) => ({ url, pages }))
    .sort((a, b) => b.pages - a.pages);
}

export default function FindingsGroups({ findings, pageUrlById }: { findings: SEOFinding[]; pageUrlById: Record<string, string> }) {
  const groups = useMemo(() => {
    const map = new Map<string, SEOFinding[]>();
    for (const f of findings) map.set(f.rule_code, [...(map.get(f.rule_code) ?? []), f]);
    return [...map.entries()]
      .map(([code, items]) => ({ code, items, severity: items.reduce((w, f) => (SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[w] ? f.severity : w), items[0].severity) }))
      .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) || b.items.length - a.items.length);
  }, [findings]);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [openItem, setOpenItem] = useState<string | null>(null);
  const [shown, setShown] = useState<Record<string, number>>({});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="finding-groups">
      {groups.map(({ code, items, severity }) => {
        const help = ruleHelp(code);
        const isOpen = openGroup === code;
        const shared = sharedUrls(code, items);
        const limit = shown[code] ?? PAGE_SIZE;
        return (
          <div key={code} className={styles.group} data-testid="finding-group">
            <button type="button" className={styles.head} aria-expanded={isOpen} onClick={() => setOpenGroup(isOpen ? null : code)}>
              <span className={styles.title}>
                <span>{ruleLabel(code)}</span>
                <span className={styles.meta}>{code}</span>
              </span>
              <span className={styles.right}>
                <StatusBadge value={severity} />
                <span className={styles.count}>{items.length} page{items.length === 1 ? "" : "s"}</span>
                <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
              </span>
            </button>
            {isOpen && (
              <div className={styles.body}>
                {help && (
                  <div className={styles.help}>
                    <span><strong>What it means:</strong> {help.means}</span>
                    <span><strong>Why it matters:</strong> {help.why}</span>
                    <span><strong>How to fix:</strong> {help.fix}</span>
                  </div>
                )}
                {shared.length > 0 && (
                  <div className={styles.callout} data-testid="shared-link">
                    <strong>Likely one shared link, not {items.length} separate problems.</strong>{" "}
                    {shared.slice(0, 3).map((s) => (
                      <span key={s.url}><code>{s.url}</code> is on {s.pages} of {items.length} pages. </span>
                    ))}
                    Fix it once in your theme (header, footer or menu) and these findings clear after the next crawl.
                  </div>
                )}
                {items.slice(0, limit).map((f) => {
                  const url = f.page_id ? pageUrlById[f.page_id] ?? f.page_id : "site-wide";
                  const expanded = openItem === f.id;
                  return (
                    <div key={f.id} className={styles.item} data-testid="finding-item">
                      <div className={styles.itemHead}>
                        <span className={styles.url}>{url}</span>
                        <button type="button" className={styles.toggle} aria-expanded={expanded} onClick={() => setOpenItem(expanded ? null : f.id)}>
                          {expanded ? "Hide details" : "Show details"}
                        </button>
                      </div>
                      {expanded && (
                        <div className={styles.evidence} data-testid="finding-evidence">
                          {describeEvidence(code, f.evidence_json as Evidence).map((line, i) => <span key={i}>{line}</span>)}
                          <span>First seen {new Date(f.first_detected_at).toLocaleDateString()}, last seen {new Date(f.last_detected_at).toLocaleDateString()}.</span>
                          {f.page_id && /^https?:/.test(url) && <a href={url} target="_blank" rel="noopener noreferrer">Open the page</a>}
                        </div>
                      )}
                    </div>
                  );
                })}
                {items.length > limit && (
                  <button type="button" className={`${styles.toggle} ${styles.more}`} onClick={() => setShown({ ...shown, [code]: limit + PAGE_SIZE })}>
                    Show {Math.min(PAGE_SIZE, items.length - limit)} more ({items.length - limit} left)
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
