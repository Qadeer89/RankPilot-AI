"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  AiUsage,
  CompetitorDomain,
  CountryOption,
  PerformanceTimeline,
  GrowthRecommendation,
  RecommendationStatus,
  KeywordIdea,
  MeResponse,
  SearchPerformance,
  SearchPerformanceIntelligence,
  Website,
  addCompetitor,
  analyzeCompetitor,
  deleteCompetitor,
  generateGrowthRecommendations,
  getPerformanceTimeline,
  getWebsiteAiUsage,
  listCountries,
  listGrowthRecommendations,
  updateGrowthRecommendationStatus,
  getMe,
  getSearchPerformance,
  getSearchPerformanceIntelligence,
  getWebsite,
  listCompetitors,
  listKeywordIdeas,
  runKeywordDiscovery,
  updateKeywordIdeaStatus,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { describeEvidence, readable } from "@/lib/recommendationText";
import RecommendationExecution from "@/components/keywords/RecommendationExecution";
import TargetMarketSettings from "@/components/keywords/TargetMarketSettings";
import styles from "./keywords.module.css";

type Tab = "overview" | "first_party" | "ai_discovery" | "country" | "clusters" | "competitors" | "opportunities" | "recommendations" | "performance";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "first_party", label: "First-Party Keywords" },
  { key: "ai_discovery", label: "AI Discovery" },
  { key: "country", label: "Country Analysis" },
  { key: "clusters", label: "Intent & Clusters" },
  { key: "competitors", label: "Competitor Gaps" },
  { key: "opportunities", label: "Opportunities & Mapping" },
  { key: "recommendations", label: "Recommendations" },
  { key: "performance", label: "Performance" },
];

function classificationBadgeClass(classification: string): string {
  if (classification === "verified_first_party" || classification === "verified_external_source") {
    return styles.badgeVerified;
  }
  if (classification === "ai_generated_idea" || classification === "ai_estimated_relevance") {
    return styles.badgeEstimate;
  }
  if (classification === "unavailable") {
    return styles.badgeUnavailable;
  }
  return styles.badge;
}

function classificationLabel(classification: string): string {
  switch (classification) {
    case "verified_first_party":
      return "Verified (your site)";
    case "verified_external_source":
      return "Verified (external)";
    case "public_search_suggestion":
      return "Public suggestion";
    case "ai_generated_idea":
      return "AI idea — not verified demand";
    case "ai_estimated_relevance":
      return "AI estimate";
    case "unavailable":
      return "Search volume unavailable";
    default:
      return classification;
  }
}

export default function KeywordWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;

  const [me, setMe] = useState<MeResponse | null>(null);
  const [website, setWebsite] = useState<Website | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);
  // Internal ISO alpha-2 code ("US"). Prefilled from the project's primary
  // target country; "" means all countries combined.
  const [country, setCountry] = useState<string>("");
  const [countries, setCountries] = useState<CountryOption[]>([]);

  const [performance, setPerformance] = useState<SearchPerformance | null>(null);
  const [intelligence, setIntelligence] = useState<SearchPerformanceIntelligence | null>(null);
  const [ideas, setIdeas] = useState<KeywordIdea[]>([]);
  const [competitors, setCompetitors] = useState<CompetitorDomain[]>([]);
  const [newCompetitorDomain, setNewCompetitorDomain] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [recommendations, setRecommendations] = useState<GrowthRecommendation[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateNote, setGenerateNote] = useState<string | null>(null);
  const [discoveryNote, setDiscoveryNote] = useState<string | null>(null);
  const [competitorNote, setCompetitorNote] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<PerformanceTimeline | null>(null);
  const [windowDays, setWindowDays] = useState(28);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);

  const token = getToken();

  useEffect(() => {
    const activeToken = getToken();
    if (!activeToken) {
      router.push("/login");
      return;
    }
    getMe(activeToken)
      .then(async (meResponse) => {
        setMe(meResponse);
        const orgId = meResponse.organizations[0]?.id;
        if (!orgId) return;
        const site = await getWebsite(activeToken, orgId, websiteId);
        setWebsite(site);
        setCountry(site.target_country ?? "");
        listCountries(activeToken).then(setCountries).catch(() => setCountries([]));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load website."));
  }, [router, websiteId]);

  const orgId = me?.organizations[0]?.id;

  const refreshAll = useCallback(async () => {
    if (!token || !orgId) return;
    setError(null);
    try {
      const [perf, intel, keywordIdeas, competitorList, recs, perfTimeline, aiUsage] = await Promise.all([
        getSearchPerformance(token, orgId, websiteId),
        getSearchPerformanceIntelligence(token, orgId, websiteId, country || undefined),
        listKeywordIdeas(token, orgId, websiteId),
        listCompetitors(token, orgId, websiteId),
        listGrowthRecommendations(token, orgId, websiteId),
        getPerformanceTimeline(token, orgId, websiteId, windowDays),
        getWebsiteAiUsage(token, orgId, websiteId),
      ]);
      setTimeline(perfTimeline);
      setUsage(aiUsage);
      setRecommendations(recs);
      setPerformance(perf);
      setIntelligence(intel);
      setIdeas(keywordIdeas);
      setCompetitors(competitorList);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load keyword data.");
    }
  }, [token, orgId, websiteId, country, windowDays]);

  useEffect(() => {
    if (orgId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      refreshAll();
    }
  }, [orgId, refreshAll]);

  async function handleRunDiscovery() {
    if (!token || !orgId) return;
    setDiscovering(true);
    setError(null);
    setDiscoveryNote(null);
    try {
      const run = await runKeywordDiscovery(token, orgId, websiteId, { country: country || undefined });
      setDiscoveryNote(
        run.ai_status === "ok"
          ? `Discovery finished: ${run.ideas.length} ideas.`
          : `${run.ai_message ?? "The AI step did not run."} Ideas from your own site data are still listed below.`
      );
      await refreshAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Keyword discovery failed.");
    } finally {
      setDiscovering(false);
    }
  }

  async function handleGenerateRecommendations() {
    if (!token || !orgId) return;
    setGenerating(true);
    setError(null);
    setGenerateNote(null);
    try {
      const generated = await generateGrowthRecommendations(token, orgId, websiteId, country || undefined);
      setRecommendations(await listGrowthRecommendations(token, orgId, websiteId));
      const scope = country ? ` for ${country}` : "";
      setGenerateNote(
        generated.length > 0
          ? `${generated.length} recommendation${generated.length === 1 ? "" : "s"} generated${scope}.`
          : `Nothing to recommend${scope} yet. Recommendations need real signals from the last 28 days: ` +
              "a query ranking on page 2 of Google (positions 11-20) with at least 10 impressions, a page losing " +
              "clicks, a query shared by several pages, or saved keyword ideas (run AI Discovery first). " +
              "Try \"All countries\" in the Country filter if this market has little data."
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate recommendations.");
    } finally {
      setGenerating(false);
    }
  }

  async function refreshRecommendations() {
    if (!token || !orgId) return;
    setRecommendations(await listGrowthRecommendations(token, orgId, websiteId));
  }

  async function handleRecommendationStatus(id: string, status: RecommendationStatus) {
    if (!token || !orgId) return;
    try {
      const updated = await updateGrowthRecommendationStatus(token, orgId, websiteId, id, status);
      setRecommendations((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update recommendation.");
    }
  }

  async function handleDismissIdea(ideaId: string) {
    if (!token || !orgId) return;
    try {
      await updateKeywordIdeaStatus(token, orgId, websiteId, ideaId, "dismissed");
      setIdeas((prev) => prev.map((i) => (i.id === ideaId ? { ...i, status: "dismissed" } : i)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update idea.");
    }
  }

  async function handleAddCompetitor(event: React.FormEvent) {
    event.preventDefault();
    if (!token || !orgId || !newCompetitorDomain.trim()) return;
    setError(null);
    try {
      await addCompetitor(token, orgId, websiteId, newCompetitorDomain.trim());
      setNewCompetitorDomain("");
      const competitorList = await listCompetitors(token, orgId, websiteId);
      setCompetitors(competitorList);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add competitor.");
    }
  }

  async function handleAnalyzeCompetitor(competitorId: string) {
    if (!token || !orgId) return;
    setAnalyzingId(competitorId);
    setError(null);
    setCompetitorNote(null);
    try {
      const result = await analyzeCompetitor(token, orgId, websiteId, competitorId);
      const crawl = `Fetched ${result.pages_fetched} public page${result.pages_fetched === 1 ? "" : "s"}` +
        (result.pages_failed ? ` (${result.pages_failed} could not be fetched)` : "") + ".";
      setCompetitorNote(
        result.ai_status === "ok"
          ? `${crawl} ${result.ideas.length} content gap idea${result.ideas.length === 1 ? "" : "s"} found.`
          : `${crawl} ${result.ai_message ?? "The AI step did not run."}`
      );
      await refreshAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Competitor analysis failed.");
    } finally {
      setAnalyzingId(null);
    }
  }

  async function handleDeleteCompetitor(competitorId: string) {
    if (!token || !orgId) return;
    try {
      await deleteCompetitor(token, orgId, websiteId, competitorId);
      setCompetitors((prev) => prev.filter((c) => c.id !== competitorId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete competitor.");
    }
  }

  if (!me || !website) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>{error ? <p className={styles.error}>{error}</p> : <p>Loading...</p>}</div>
      </div>
    );
  }

  const activeIdeas = ideas.filter((i) => i.status !== "dismissed");
  const aiIdeas = ideas.filter((i) => i.source === "ai_generated" || i.source === "seed");
  const competitorIdeas = ideas.filter((i) => i.source === "competitor_gap");

  const clustersByIntent = new Map<string, KeywordIdea[]>();
  for (const idea of activeIdeas) {
    const list = clustersByIntent.get(idea.search_intent) ?? [];
    list.push(idea);
    clustersByIntent.set(idea.search_intent, list);
  }

  const clustersByContentType = new Map<string, KeywordIdea[]>();
  for (const idea of activeIdeas) {
    const key = idea.recommended_content_type ?? "unspecified";
    const list = clustersByContentType.get(key) ?? [];
    list.push(idea);
    clustersByContentType.set(key, list);
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <div>
            <Link href={`/dashboard/websites/${websiteId}`} className={styles.backLink}>
              ← Back to {website.display_name}
            </Link>
            <h1>Keyword Intelligence</h1>
            <p className={styles.subtitle}>
              First-party Search Console data, AI-assisted discovery, and public competitor content analysis --
              every number here is labeled as verified or estimated, never guessed as fact.
            </p>
          </div>
          <div className={styles.countrySelector}>
            <label htmlFor="country-filter" style={{ fontSize: 13, color: "var(--rp-muted)" }}>
              Country
            </label>
            <select
              id="country-filter"
              className={styles.select}
              value={country}
              onChange={(e) => setCountry(e.target.value)}
            >
              <option value="">All countries</option>
              {[
                ...(website.target_country ? [website.target_country] : []),
                ...website.additional_target_countries,
              ].map((code) => (
                <option key={code} value={code}>
                  {countries.find((c) => c.code === code)?.name ?? code} ({code})
                </option>
              ))}
              {country &&
                ![website.target_country, ...website.additional_target_countries].includes(country) && (
                  <option value={country}>{country}</option>
                )}
            </select>
          </div>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}

        <div className={styles.tabs}>
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`${styles.tab} ${tab === t.key ? styles.tabActive : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "overview" && (
          <div className={styles.card}>
            <h2>Overview</h2>
            <div className={styles.metricGrid}>
              <div className={styles.metricTile}>
                <div className={styles.metricLabel}>GSC queries (first-party)</div>
                <div className={styles.metricValue}>{performance?.rows.length ?? 0}</div>
              </div>
              <div className={styles.metricTile}>
                <div className={styles.metricLabel}>Keyword ideas</div>
                <div className={styles.metricValue}>{activeIdeas.length}</div>
              </div>
              <div className={styles.metricTile}>
                <div className={styles.metricLabel}>New queries (14d)</div>
                <div className={styles.metricValue}>{intelligence?.new_queries.length ?? 0}</div>
              </div>
              <div className={styles.metricTile}>
                <div className={styles.metricLabel}>Pages declining</div>
                <div className={styles.metricValue}>
                  {intelligence?.declining_pages.filter((p) => p.signals.some((s) => s.includes("declining") || s === "position_worsening")).length ?? 0}
                </div>
              </div>
              <div className={styles.metricTile}>
                <div className={styles.metricLabel}>Competitors tracked</div>
                <div className={styles.metricValue}>{competitors.length}</div>
              </div>
            </div>
            {token && orgId && (
              <TargetMarketSettings
                token={token}
                organizationId={orgId}
                website={website}
                countries={countries}
                onSaved={(updated) => {
                  setWebsite(updated);
                  setCountry(updated.target_country ?? "");
                }}
              />
            )}
            {usage && (
              <p className={styles.freshnessNote}>
                AI usage, last {usage.days} days: about ${usage.total_estimated_cost_usd.toFixed(2)} across{" "}
                {usage.by_agent_type.reduce((sum, a) => sum + a.runs, 0)} runs. {usage.note}
              </p>
            )}
            {!website.search_console_site_url && (
              <p className={styles.empty}>
                Connect Google Search Console (Integrations tab) to unlock first-party keyword data and
                country-specific analysis.
              </p>
            )}
          </div>
        )}

        {tab === "first_party" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>First-Party Keywords (Google Search Console)</h2>
            </div>
            {performance && <p className={styles.freshnessNote}>{performance.freshness_note}</p>}
            {!performance || performance.rows.length === 0 ? (
              <p className={styles.empty}>No Search Console data synced yet.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Query</th>
                    <th>Country</th>
                    <th>Device</th>
                    <th>Clicks</th>
                    <th>Impressions</th>
                    <th>CTR</th>
                    <th>Avg. position</th>
                    <th>Mapped page</th>
                  </tr>
                </thead>
                <tbody>
                  {performance.rows.slice(0, 100).map((row, i) => (
                    <tr key={i}>
                      <td>{row.query}</td>
                      <td>{row.country ?? "—"}</td>
                      <td>{row.device ?? "—"}</td>
                      <td>{row.clicks}</td>
                      <td>{row.impressions}</td>
                      <td>{(row.ctr * 100).toFixed(1)}%</td>
                      <td>{row.average_position.toFixed(1)}</td>
                      <td>{row.page_id ? "Yes" : "Not yet crawled"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "ai_discovery" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>AI Keyword & Topic Discovery</h2>
              <button type="button" className={styles.primaryButton} onClick={handleRunDiscovery} disabled={discovering}>
                {discovering ? "Running..." : "Run discovery"}
              </button>
            </div>
            <p className={styles.freshnessNote}>
              Seed keywords come from your own crawled pages and Search Console queries. AI ideas are relevance
              estimates, never verified search demand.
            </p>
            {discoveryNote && (
              <p className={styles.freshnessNote} role="status">
                {discoveryNote}
              </p>
            )}
            {aiIdeas.length === 0 ? (
              <p className={styles.empty}>No keyword ideas yet -- run discovery to generate some.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Keyword</th>
                    <th>Intent</th>
                    <th>Content type</th>
                    <th>Classification</th>
                    <th>Confidence</th>
                    <th>Rationale</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {aiIdeas.map((idea) => (
                    <tr key={idea.id}>
                      <td>{idea.keyword}</td>
                      <td>{idea.search_intent}</td>
                      <td>{idea.recommended_content_type ?? "—"}</td>
                      <td>
                        <span className={`${styles.badge} ${classificationBadgeClass(idea.data_classification)}`}>
                          {classificationLabel(idea.data_classification)}
                        </span>
                      </td>
                      <td>{(idea.confidence * 100).toFixed(0)}%</td>
                      <td>{idea.rationale}</td>
                      <td>
                        {idea.status !== "dismissed" && (
                          <button type="button" className={styles.secondaryButton} onClick={() => handleDismissIdea(idea.id)}>
                            Dismiss
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "country" && (
          <div className={styles.card}>
            <h2>Country Analysis {country ? `— ${country}` : "(all countries combined)"}</h2>
            <p className={styles.freshnessNote}>
              Choose a country above (your target markets are listed first) to scope every signal below to one
              market -- results are never blended across countries.
            </p>

            <div className={styles.clusterGroup}>
              <div className={styles.clusterTitle}>New queries (last 14 days)</div>
              {!intelligence || intelligence.new_queries.length === 0 ? (
                <p className={styles.empty}>No new queries detected.</p>
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Query</th>
                      <th>Impressions</th>
                      <th>Clicks</th>
                      <th>Avg. position</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intelligence.new_queries.map((q, i) => (
                      <tr key={i}>
                        <td>{q.query}</td>
                        <td>{q.impressions}</td>
                        <td>{q.clicks}</td>
                        <td>{q.average_position.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className={styles.clusterGroup}>
              <div className={styles.clusterTitle}>Ranking improvement opportunities (page 2 of Google)</div>
              {!intelligence || intelligence.ranking_improvement_opportunities.length === 0 ? (
                <p className={styles.empty}>None found.</p>
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Query</th>
                      <th>Impressions</th>
                      <th>Avg. position</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intelligence.ranking_improvement_opportunities.map((o, i) => (
                      <tr key={i}>
                        <td>{o.query}</td>
                        <td>{o.impressions}</td>
                        <td>{o.average_position.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className={styles.clusterGroup}>
              <div className={styles.clusterTitle}>Keyword cannibalization candidates</div>
              {!intelligence || intelligence.keyword_cannibalization.length === 0 ? (
                <p className={styles.empty}>None found.</p>
              ) : (
                intelligence.keyword_cannibalization.map((c, i) => (
                  <div key={i} className={styles.domainRow}>
                    <span>{c.query}</span>
                    <span className={styles.subtitle}>{c.pages.length} pages competing</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {tab === "clusters" && (
          <div className={styles.card}>
            <h2>Search Intent</h2>
            {[...clustersByIntent.entries()].map(([intent, list]) => (
              <div key={intent} className={styles.clusterGroup}>
                <div className={styles.clusterTitle}>
                  {intent} ({list.length})
                </div>
                {list.map((idea) => (
                  <div key={idea.id} className={styles.domainRow}>
                    <span>{idea.keyword}</span>
                    <span className={styles.subtitle}>{idea.recommended_content_type ?? "—"}</span>
                  </div>
                ))}
              </div>
            ))}
            {activeIdeas.length === 0 && <p className={styles.empty}>No keyword ideas yet.</p>}

            <h2 style={{ marginTop: 8 }}>Content Clusters (by recommended content type)</h2>
            {[...clustersByContentType.entries()].map(([type, list]) => (
              <div key={type} className={styles.clusterGroup}>
                <div className={styles.clusterTitle}>
                  {type} ({list.length})
                </div>
                {list.map((idea) => (
                  <div key={idea.id} className={styles.domainRow}>
                    <span>{idea.keyword}</span>
                    <span className={styles.subtitle}>{idea.search_intent}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {tab === "competitors" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Competitor Content Gaps</h2>
            </div>
            <p className={styles.freshnessNote}>
              Only publicly accessible pages are analyzed -- never a competitor&apos;s private traffic, rankings,
              backlinks or search volume.
            </p>
            {competitorNote && (
              <p className={styles.freshnessNote} role="status">
                {competitorNote}
              </p>
            )}
            <form className={styles.formRow} onSubmit={handleAddCompetitor}>
              <input
                className={styles.input}
                placeholder="competitor.com"
                value={newCompetitorDomain}
                onChange={(e) => setNewCompetitorDomain(e.target.value)}
                style={{ flex: 1 }}
              />
              <button type="submit" className={styles.primaryButton}>
                Add competitor
              </button>
            </form>

            {competitors.length === 0 ? (
              <p className={styles.empty}>No competitors added yet.</p>
            ) : (
              competitors.map((c) => (
                <div key={c.id} className={styles.domainRow}>
                  <div>
                    <div>{c.domain}</div>
                    <div className={styles.subtitle}>
                      {c.last_analyzed_at ? `Last analyzed ${new Date(c.last_analyzed_at).toLocaleString()}` : "Not analyzed yet"}
                    </div>
                  </div>
                  <div className={styles.domainActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => handleAnalyzeCompetitor(c.id)}
                      disabled={analyzingId === c.id}
                    >
                      {analyzingId === c.id ? "Analyzing..." : "Analyze"}
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => handleDeleteCompetitor(c.id)}>
                      Remove
                    </button>
                  </div>
                </div>
              ))
            )}

            <h2 style={{ marginTop: 8 }}>Content gap ideas</h2>
            {competitorIdeas.length === 0 ? (
              <p className={styles.empty}>No content gaps found yet -- add a competitor and click Analyze.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Topic</th>
                    <th>Content type</th>
                    <th>Confidence</th>
                    <th>Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {competitorIdeas.map((idea) => (
                    <tr key={idea.id}>
                      <td>{idea.keyword}</td>
                      <td>{idea.recommended_content_type ?? "—"}</td>
                      <td>{(idea.confidence * 100).toFixed(0)}%</td>
                      <td>{idea.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "opportunities" && (
          <div className={styles.card}>
            <h2>Opportunities & Keyword-to-Page Mapping</h2>
            <p className={styles.freshnessNote}>
              Highest-confidence ideas not yet dismissed, across first-party signals, AI discovery and
              competitor gaps.
            </p>
            {activeIdeas.length === 0 ? (
              <p className={styles.empty}>Nothing here yet.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Idea</th>
                    <th>Source</th>
                    <th>Content type</th>
                    <th>Classification</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {[...activeIdeas]
                    .sort((a, b) => b.confidence - a.confidence)
                    .slice(0, 50)
                    .map((idea) => (
                      <tr key={idea.id}>
                        <td>{idea.keyword}</td>
                        <td>{idea.source}</td>
                        <td>{idea.recommended_content_type ?? "—"}</td>
                        <td>
                          <span className={`${styles.badge} ${classificationBadgeClass(idea.data_classification)}`}>
                            {classificationLabel(idea.data_classification)}
                          </span>
                        </td>
                        <td>{(idea.confidence * 100).toFixed(0)}%</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "recommendations" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Growth Recommendations</h2>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={handleGenerateRecommendations}
                disabled={generating}
              >
                {generating ? "Generating..." : "Generate from current data"}
              </button>
            </div>
            <p className={styles.freshnessNote}>
              Built from your Search Console data and stored keyword ideas. Nothing here is a promise of a
              ranking or traffic result, and each change needs your approval.
            </p>
            {generateNote && (
              <p className={styles.freshnessNote} role="status">
                {generateNote}
              </p>
            )}
            {recommendations.length === 0 ? (
              <p className={styles.empty}>No recommendations yet.</p>
            ) : (
              recommendations.map((rec) => (
                <div key={rec.id} className={styles.recCard}>
                  <div className={styles.cardHeader}>
                    <strong>{readable(rec.title)}</strong>
                    <span className={styles.badge}>
                      {rec.lifecycle?.applied_manually ? "applied (manually)" : (rec.lifecycle?.lifecycle_status ?? rec.status).replaceAll("_", " ")} · {rec.priority} priority · {rec.difficulty} effort
                    </span>
                  </div>
                  <p>
                    <strong>Why:</strong> {rec.problem}
                  </p>
                  <p>
                    <strong>Do:</strong> {readable(rec.recommended_action)}
                  </p>
                  <p>
                    <strong>Expected benefit:</strong> {rec.expected_benefit}
                  </p>
                  <p>
                    <strong>How to check:</strong> {rec.validation_method}
                  </p>
                  <p className={styles.subtitle}>
                    Source: {rec.data_source.replaceAll("_", " ")}
                    {rec.target_country ? ` · Country: ${rec.target_country}` : ""} ·{" "}
                    {rec.automation_available ? "Can be applied automatically" : "Manual change"} · Evidence:{" "}
                    {describeEvidence(rec.evidence_json)}
                  </p>
                  {rec.status === "open" && (
                    <div className={styles.domainActions}>
                      <button
                        type="button"
                        className={styles.primaryButton}
                        onClick={() => handleRecommendationStatus(rec.id, "approved")}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => handleRecommendationStatus(rec.id, "rejected")}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                  {rec.status === "approved" && (
                    <div className={styles.domainActions}>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => handleRecommendationStatus(rec.id, "done")}
                      >
                        Mark as done (I applied it myself)
                      </button>
                    </div>
                  )}
                  {token && orgId && (
                    <RecommendationExecution
                      token={token}
                      organizationId={orgId}
                      websiteId={websiteId}
                      rec={rec}
                      onChanged={refreshRecommendations}
                    />
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {tab === "performance" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>SEO Improvement Timeline</h2>
              <select
                className={styles.select}
                aria-label="Comparison window"
                value={windowDays}
                onChange={(e) => setWindowDays(Number(e.target.value))}
              >
                <option value={7}>7 days before / after</option>
                <option value={28}>28 days before / after</option>
                <option value={90}>90 days before / after</option>
              </select>
            </div>
            {timeline && <p className={styles.freshnessNote}>{timeline.caveat}</p>}
            {!timeline || timeline.entries.length === 0 ? (
              <p className={styles.empty}>No published changes yet. Changes RankPilot applies to a page appear here.</p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Page / change</th>
                    <th>Published</th>
                    <th>Check</th>
                    <th>Clicks</th>
                    <th>Impressions</th>
                    <th>CTR</th>
                    <th>Avg. position</th>
                    <th>GA4 organic landing sessions</th>
                  </tr>
                </thead>
                <tbody>
                  {timeline.entries.map((entry) => {
                    const pair = (
                      before: number | null | undefined,
                      after: number | null | undefined,
                      format: (n: number) => string
                    ) =>
                      `${before == null ? "no data" : format(before)} → ${after == null ? "no data" : format(after)}`;
                    return (
                      <tr key={entry.change_id}>
                        <td>
                          {entry.page_url ?? "Unknown page"}
                          <div className={styles.subtitle}>{entry.operation ?? "change"}</div>
                        </td>
                        <td>{new Date(entry.implemented_at).toLocaleDateString()}</td>
                        <td>
                          {entry.validation_status}
                          {!entry.after_window_complete && <div className={styles.subtitle}>after-window still filling</div>}
                        </td>
                        <td>{pair(entry.before?.clicks, entry.after?.clicks, String)}</td>
                        <td>{pair(entry.before?.impressions, entry.after?.impressions, String)}</td>
                        <td>{pair(entry.before?.ctr, entry.after?.ctr, (n) => `${(n * 100).toFixed(1)}%`)}</td>
                        <td>{pair(entry.before?.average_position, entry.after?.average_position, (n) => n.toFixed(1))}</td>
                        <td>
                          {pair(entry.organic_landing_before?.sessions, entry.organic_landing_after?.sessions, String)}
                          <div className={styles.subtitle}>GA4 engagement, not a ranking metric</div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
