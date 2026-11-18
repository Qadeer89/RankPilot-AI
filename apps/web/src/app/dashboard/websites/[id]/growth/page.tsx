"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError, BusinessProfile, GrowthJourney, GrowthPlan, MeResponse, UnifiedRecommendationList,
  getBusinessProfile, getGrowthJourney, getGrowthPlan, getMe, listUnifiedRecommendations, saveBusinessProfile, suggestBusinessProfile,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "./growth.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const STATUS: Record<string, string> = { todo: "To do", done: "Done", blocked: "Waiting" };
const PRIORITIES = ["", "critical", "high", "medium", "low"];
const TYPES = ["", "technical", "on_page", "content", "keyword", "product", "internal_linking", "competitor_gap"];
const label = (v: string) => (v ? v.replace(/_/g, " ") : "All");

export default function GrowthPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;
  const [journey, setJourney] = useState<GrowthJourney | null>(null);
  const [plan, setPlan] = useState<GrowthPlan | null>(null);
  const [profile, setProfile] = useState<BusinessProfile | null>(null);
  const [recs, setRecs] = useState<UnifiedRecommendationList | null>(null);
  const [priority, setPriority] = useState("");
  const [type, setType] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ business_type: "", industry: "", offerings: "", target_customers: "", objective: "", known_competitors: "" });

  const fillForm = (p: BusinessProfile) =>
    setForm({ business_type: p.business_type ?? "", industry: p.industry ?? "", offerings: p.offerings.join("\n"), target_customers: p.target_customers.join("\n"),
              objective: p.objective ?? "", known_competitors: p.known_competitors.join("\n") });

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);

  const loadCore = useCallback(() => {
    if (!token || !orgId) return;
    Promise.all([getGrowthJourney(token, orgId, websiteId), getGrowthPlan(token, orgId, websiteId), getBusinessProfile(token, orgId, websiteId)])
      .then(([j, p, b]) => { setJourney(j); setPlan(p); setProfile(b); fillForm(b); })
      .catch((e) => setError(msg(e)));
  }, [token, orgId, websiteId]);
  useEffect(loadCore, [loadCore]);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    listUnifiedRecommendations(token, orgId, websiteId, { priority, type, q: query })
      .then((r) => !cancelled && setRecs(r))
      .catch((e) => !cancelled && setError(msg(e)));
    return () => { cancelled = true; };
  }, [token, orgId, websiteId, priority, type, query]);

  async function save() {
    if (!token || !orgId) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const saved = await saveBusinessProfile(token, orgId, websiteId, {
        business_type: form.business_type, industry: form.industry, offerings: lines(form.offerings), target_customers: lines(form.target_customers),
        objective: form.objective, known_competitors: lines(form.known_competitors),
      });
      setProfile(saved); fillForm(saved); setNotice("Business profile confirmed."); loadCore();
    } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  }

  async function suggest() {
    if (!token || !orgId) return;
    setBusy(true); setError(null); setNotice(null);
    try { setProfile(await suggestBusinessProfile(token, orgId, websiteId)); } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  }

  function useSuggestions() {
    const s = profile?.ai_suggestions;
    if (!s) return;
    setForm((f) => ({
      ...f, business_type: s.business_type ?? f.business_type, industry: s.industry ?? f.industry,
      offerings: (s.offerings ?? []).join("\n") || f.offerings, target_customers: (s.audiences ?? []).join("\n") || f.target_customers,
      objective: s.objective_ideas?.[0] ?? f.objective,
    }));
    setNotice("Suggestions copied into the form. Review and edit them, then confirm.");
  }

  const s = profile?.ai_suggestions;
  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <Link href={`/dashboard/websites/${websiteId}`} className={styles.back}>← Back to project</Link>
          <h1>Growth Plan</h1>
          <p className={styles.sub}>What RankPilot found, what to do next, and what each step is based on.</p>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {notice && <div className={styles.note} role="status">{notice}</div>}

        {journey && (
          <section className={styles.card} aria-label="Where you are">
            <h2>Where you are</h2>
            <p data-testid="journey-message">{journey.message}</p>
            <div className={styles.tableWrap}>
              <table className={styles.table} data-testid="panels">
                <thead><tr><th>Measure</th><th>Status</th><th>Source</th></tr></thead>
                <tbody>
                  {journey.panels.map((p) => (
                    <tr key={p.panel}><td>{p.panel}</td><td>{p.available ? "Available" : `Not available — ${p.reason}`}</td><td>{p.source}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>Next actions</h3>
            <ul className={styles.list} data-testid="next-actions">
              {journey.next_actions.map((a) => <li key={a.key}><strong>{a.text}</strong>{a.detail && <span className={styles.small}>{a.detail}</span>}</li>)}
            </ul>
            <p className={styles.small}>{journey.expectations}</p>
          </section>
        )}

        <section className={styles.card} aria-label="Business profile">
          <h2>Business profile {profile?.confirmed && <span className={`${styles.badge} ${styles.good}`}>Confirmed</span>}</h2>
          <p className={styles.small}>Tell RankPilot what the business is. Target countries and language come from the project settings{profile?.target_countries?.length ? ` (${profile.target_countries.join(", ")})` : ""}.</p>
          <div className={styles.row}>
            <button className={styles.btn} onClick={suggest} disabled={busy}>Suggest from my website</button>
          </div>
          {s && (
            <div className={styles.suggest} data-testid="ai-suggestions">
              <strong>AI suggestions — not saved until you confirm</strong>
              <span className={styles.small}>{s.label}</span>
              <span>Type: {s.business_type ?? "—"} · Industry: {s.industry ?? "—"}</span>
              <span>Offerings found on your site: {(s.offerings ?? []).join(", ") || "—"}</span>
              {!!s.dropped_unsupported_offerings?.length && <span className={styles.small}>Left out because your site does not mention them: {s.dropped_unsupported_offerings.join(", ")}</span>}
              <button className={styles.btn} onClick={useSuggestions}>Copy into the form</button>
            </div>
          )}
          <div className={styles.form}>
            <label>Business type<input value={form.business_type} onChange={(e) => setForm({ ...form, business_type: e.target.value })} /></label>
            <label>Industry<input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></label>
            <label>Products or services (one per line)<textarea rows={3} value={form.offerings} onChange={(e) => setForm({ ...form, offerings: e.target.value })} /></label>
            <label>Target customers (one per line)<textarea rows={2} value={form.target_customers} onChange={(e) => setForm({ ...form, target_customers: e.target.value })} /></label>
            <label>Business objective<textarea rows={2} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></label>
            <label>Known competitors (domains, one per line)<textarea rows={2} value={form.known_competitors} onChange={(e) => setForm({ ...form, known_competitors: e.target.value })} /></label>
            <div className={styles.row}><button className={styles.btn} onClick={save} disabled={busy}>Confirm business profile</button></div>
          </div>
        </section>

        {plan && (
          <section className={styles.card} aria-label="First 30 days">
            <h2>Your first 30 days</h2>
            <p className={styles.note} data-testid="plan-pace">{plan.pace_note}</p>
            {plan.stages.map((st) => (
              <div key={st.days} className={styles.stage}>
                <h3>Days {st.days}: {st.title}</h3>
                <ul className={styles.list}>
                  {st.items.map((i) => (
                    <li key={i.text}><span><strong>{i.text}</strong> <span className={styles.badge}>{STATUS[i.status]}</span></span><span className={styles.small}>{i.basis}</span></li>
                  ))}
                </ul>
              </div>
            ))}
            <p className={styles.small} data-testid="plan-disclaimer">{plan.disclaimer}</p>
          </section>
        )}

        <section className={styles.card} aria-label="Recommendations">
          <h2>Recommendations {recs && <span className={styles.small}>({recs.total})</span>}</h2>
          <div className={styles.controls}>
            <label>Priority<select value={priority} onChange={(e) => setPriority(e.target.value)}>{PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}</select></label>
            <label>Type<select value={type} onChange={(e) => setType(e.target.value)}>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></label>
            <label>Search<input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          </div>
          {recs && recs.items.length === 0 && <p className={styles.empty}>No recommendations match.</p>}
          {recs?.items.map((r) => (
            <article key={r.id} className={styles.rec} data-testid="rec">
              <h3>{r.title}</h3>
              <div className={styles.row}>
                <span className={styles.badge}>{r.priority}</span><span className={styles.badge}>{label(r.type)}</span><span className={styles.badge}>{label(r.stage)}</span>
                <span className={styles.small}>Source: {r.data_source}{r.affected ? ` · ${r.affected}` : ""}</span>
              </div>
              <span>{r.problem}</span>
              <span className={styles.small}>Why it matters: {r.why_it_matters}</span>
              <span className={styles.small}>How it is checked: {r.validation}</span>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
