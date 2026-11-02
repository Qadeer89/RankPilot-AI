"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  ChangeRecord,
  CrawlJob,
  Opportunity,
  OpportunityProposal,
  Page,
  Report,
  SEOFinding,
  SEOTask,
  SearchPerformance,
  Website,
  WebsiteConnection,
  approveTask,
  connectWordPress,
  createProposal,
  createTasks,
  disconnectWordPress,
  executeTask,
  getMe,
  getSearchPerformance,
  getSearchProperties,
  getWebsite,
  listConnections,
  listCrawls,
  listFindings,
  listOpportunities,
  listPages,
  listReports,
  listTasks,
  pauseWebsite,
  rejectTask,
  rollbackChange,
  selectSearchProperty,
  startGoogleConnect,
  syncSearchConsole,
  triggerCrawl,
  updateWebsiteSettings,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import styles from "./detail.module.css";

const TABS = [
  "overview",
  "crawls",
  "findings",
  "opportunities",
  "tasks",
  "integrations",
  "reports",
] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  crawls: "Crawls",
  findings: "Findings",
  opportunities: "Opportunities",
  tasks: "Tasks",
  integrations: "Integrations",
  reports: "Reports",
};

function badgeClass(value: string): string {
  const good = ["verified", "passed", "completed", "indexable", "sent", "approved", "connected"];
  const bad = ["failed", "unverified", "rejected", "error", "disconnected"];
  const warn = ["pending", "executing", "running", "skipped_not_configured", "noindex"];
  if (good.includes(value)) return `${styles.badge} ${styles.badgeGood}`;
  if (bad.includes(value)) return `${styles.badge} ${styles.badgeBad}`;
  if (warn.includes(value)) return `${styles.badge} ${styles.badgeWarn}`;
  return styles.badge;
}

export default function WebsiteDetailClient() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const websiteId = params.id;

  const tokenRef = useRef<string | null>(null);
  const orgIdRef = useRef<string | null>(null);

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [website, setWebsite] = useState<Website | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [crawls, setCrawls] = useState<CrawlJob[]>([]);
  const [pages, setPages] = useState<Page[]>([]);
  const [findings, setFindings] = useState<SEOFinding[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [proposals, setProposals] = useState<Record<string, OpportunityProposal>>({});
  const [tasks, setTasks] = useState<SEOTask[]>([]);
  const [connections, setConnections] = useState<WebsiteConnection[]>([]);
  const [searchPerformance, setSearchPerformance] = useState<SearchPerformance | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [changeRecords, setChangeRecords] = useState<Record<string, ChangeRecord>>({});

  const [wpUsername, setWpUsername] = useState("");
  const [wpPassword, setWpPassword] = useState("");
  const [sitePropertyInput, setSitePropertyInput] = useState("");

  const pageUrlById = Object.fromEntries(pages.map((p) => [p.id, p.normalized_url]));

  const refreshAll = useCallback(async () => {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    const [site, crawlList, pageList, findingList, opportunityList, taskList, connectionList, reportList] =
      await Promise.all([
        getWebsite(token, orgId, websiteId),
        listCrawls(token, orgId, websiteId),
        listPages(token, orgId, websiteId),
        listFindings(token, orgId, websiteId),
        listOpportunities(token, orgId, websiteId),
        listTasks(token, orgId, websiteId),
        listConnections(token, orgId, websiteId),
        listReports(token, orgId, websiteId),
      ]);
    setWebsite(site);
    setCrawls(crawlList);
    setPages(pageList);
    setFindings(findingList);
    setOpportunities(opportunityList);
    setTasks(taskList);
    setConnections(connectionList);
    setReports(reportList);

    if (site.search_console_site_url) {
      try {
        setSearchPerformance(await getSearchPerformance(token, orgId, websiteId));
      } catch {
        // Search Console may not actually be connected yet; ignore.
      }
    }
  }, [websiteId]);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    tokenRef.current = token;

    getMe(token)
      .then(async (me) => {
        if (me.organizations.length === 0) return;
        orgIdRef.current = me.organizations[0].id;
        await refreshAll();
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.push("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load website.");
      })
      .finally(() => setLoading(false));
  }, [router, refreshAll]);

  async function handleTriggerCrawl() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await triggerCrawl(token, orgId, websiteId);
      setCrawls(await listCrawls(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to trigger crawl.");
    }
  }

  async function handlePause() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      setWebsite(await pauseWebsite(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to pause website.");
    }
  }

  async function handleToggleAutoExecute() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId || !website) return;
    setError(null);
    try {
      const next = !website.automation_policy.auto_execute_risk_tier_1;
      setWebsite(await updateWebsiteSettings(token, orgId, websiteId, { auto_execute_risk_tier_1: next }));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to update settings.");
    }
  }

  async function handleGetProposal(opportunityId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const proposal = await createProposal(token, orgId, websiteId, opportunityId);
      setProposals((prev) => ({ ...prev, [opportunityId]: proposal }));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to get an AI proposal.");
    }
  }

  async function handleCreateTask(opportunityId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    const proposal = proposals[opportunityId];
    if (!token || !orgId || !proposal) return;
    setError(null);
    try {
      await createTasks(token, orgId, websiteId, opportunityId, proposal);
      setTasks(await listTasks(token, orgId, websiteId));
      setActiveTab("tasks");
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to create a task.");
    }
  }

  async function handleTaskAction(taskId: string, action: "approve" | "reject" | "execute") {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      if (action === "approve") await approveTask(token, orgId, websiteId, taskId);
      else if (action === "reject") await rejectTask(token, orgId, websiteId, taskId);
      else {
        const changeRecord = await executeTask(token, orgId, websiteId, taskId);
        setChangeRecords((prev) => ({ ...prev, [taskId]: changeRecord }));
      }
      setTasks(await listTasks(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : `Failed to ${action} task.`);
    }
  }

  async function handleRollback(taskId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    const changeRecord = changeRecords[taskId];
    if (!token || !orgId || !changeRecord) return;
    setError(null);
    try {
      await rollbackChange(token, orgId, websiteId, changeRecord.id);
      setTasks(await listTasks(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to roll back.");
    }
  }

  async function handleConnectWordPress() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await connectWordPress(token, orgId, websiteId, wpUsername, wpPassword);
      setWpUsername("");
      setWpPassword("");
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to connect WordPress.");
    }
  }

  async function handleDisconnectWordPress() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await disconnectWordPress(token, orgId, websiteId);
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect WordPress.");
    }
  }

  async function handleConnectGoogle() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const { authorization_url } = await startGoogleConnect(token, orgId);
      window.location.href = authorization_url;
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to start Google connect.");
    }
  }

  async function handleLoadProperties() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const { site_urls } = await getSearchProperties(token, orgId, websiteId);
      if (site_urls.length > 0) setSitePropertyInput(site_urls[0]);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to load properties.");
    }
  }

  async function handleSelectProperty() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId || !sitePropertyInput) return;
    setError(null);
    try {
      setWebsite(await selectSearchProperty(token, orgId, websiteId, sitePropertyInput));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to select property.");
    }
  }

  async function handleSyncSearchConsole() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await syncSearchConsole(token, orgId, websiteId);
      setSearchPerformance(await getSearchPerformance(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to sync Search Console.");
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  if (!website) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>
          {error ? <p className={styles.error}>{error}</p> : <p>Website not found.</p>}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Link className={styles.backLink} href="/dashboard">
          ← Back to dashboard
        </Link>

        <div className={styles.header}>
          <h1>{website.display_name}</h1>
          <span className={badgeClass(website.verification_status)}>{website.verification_status}</span>
        </div>
        <span>{website.canonical_url}</span>

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.tabs}>
          {TABS.map((tab) => (
            <button
              key={tab}
              className={`${styles.tab} ${activeTab === tab ? styles.tabActive : ""}`}
              onClick={() => setActiveTab(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        {activeTab === "overview" && (
          <div className={styles.card}>
            <h2>Settings</h2>
            <div className={styles.row}>
              <div className={styles.rowMain}>
                <span>Website status</span>
                <span className={styles.rowMeta}>Pausing blocks all automated writes immediately.</span>
              </div>
              <div className={styles.actions}>
                <span className={badgeClass(website.status)}>{website.status}</span>
                {website.status === "active" && (
                  <button className={styles.button} onClick={handlePause}>
                    Pause automation
                  </button>
                )}
              </div>
            </div>
            <div className={styles.row}>
              <div className={styles.rowMain}>
                <span>Crawl budget</span>
                <span className={styles.rowMeta}>{website.crawl_budget} pages per crawl</span>
              </div>
            </div>
            <div className={styles.row}>
              <div className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={Boolean(website.automation_policy.auto_execute_risk_tier_1)}
                  onChange={handleToggleAutoExecute}
                  id="auto-execute"
                />
                <label htmlFor="auto-execute">
                  Auto-execute low-risk (tier 1) changes without approval
                </label>
              </div>
            </div>
          </div>
        )}

        {activeTab === "crawls" && (
          <div className={styles.card}>
            <h2>Crawls</h2>
            <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleTriggerCrawl}>
              Run a crawl now
            </button>
            {crawls.length === 0 && <p className={styles.empty}>No crawls yet.</p>}
            {crawls.map((crawl) => (
              <div key={crawl.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span>{crawl.trigger} crawl</span>
                  <span className={styles.rowMeta}>
                    {crawl.pages_fetched}/{crawl.pages_requested} pages fetched
                    {crawl.error_summary ? ` — ${crawl.error_summary}` : ""}
                  </span>
                </div>
                <span className={badgeClass(crawl.status)}>{crawl.status}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === "findings" && (
          <div className={styles.card}>
            <h2>Findings</h2>
            {findings.length === 0 && <p className={styles.empty}>No findings yet — run a crawl first.</p>}
            {findings.map((finding) => (
              <div key={finding.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span>{finding.rule_code}</span>
                  <span className={styles.rowMeta}>
                    {finding.page_id ? pageUrlById[finding.page_id] ?? finding.page_id : "site-wide"}
                  </span>
                </div>
                <div className={styles.actions}>
                  <span className={badgeClass(finding.severity)}>{finding.severity}</span>
                  <span className={badgeClass(finding.status)}>{finding.status}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === "opportunities" && (
          <div className={styles.card}>
            <h2>Opportunities</h2>
            {opportunities.length === 0 && (
              <p className={styles.empty}>No opportunities yet — run a crawl first.</p>
            )}
            {opportunities.map((opportunity) => (
              <div key={opportunity.id} className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className={styles.row} style={{ border: "none", padding: 0 }}>
                  <div className={styles.rowMain}>
                    <span>{opportunity.title}</span>
                    <span className={styles.rowMeta}>
                      score {opportunity.score.toFixed(2)} · risk tier {opportunity.risk_tier} ·{" "}
                      {opportunity.rationale}
                    </span>
                  </div>
                  <div className={styles.actions}>
                    <span className={badgeClass(opportunity.status)}>{opportunity.status}</span>
                    {opportunity.status === "open" && !proposals[opportunity.id] && (
                      <button className={styles.button} onClick={() => handleGetProposal(opportunity.id)}>
                        Get AI proposal
                      </button>
                    )}
                  </div>
                </div>
                {proposals[opportunity.id] && (
                  <div className={styles.proposalBox}>
                    <strong>{proposals[opportunity.id].summary}</strong>
                    {proposals[opportunity.id].proposed_actions.map((action, i) => (
                      <div key={i} className={styles.proposalActionLine}>
                        {action.operation} {action.target_url} → &quot;{action.value}&quot;
                      </div>
                    ))}
                    <span className={styles.rowMeta}>
                      confidence {proposals[opportunity.id].confidence.toFixed(2)} · risk tier{" "}
                      {proposals[opportunity.id].risk_tier}
                    </span>
                    <button
                      className={`${styles.button} ${styles.buttonPrimary}`}
                      onClick={() => handleCreateTask(opportunity.id)}
                    >
                      Create task from this proposal
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {activeTab === "tasks" && (
          <div className={styles.card}>
            <h2>Tasks</h2>
            {tasks.length === 0 && <p className={styles.empty}>No tasks yet.</p>}
            {tasks.map((task) => (
              <div key={task.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span>{task.task_type}</span>
                  <span className={styles.rowMeta}>
                    risk tier {task.risk_tier} · approval: {task.approval_status}
                  </span>
                </div>
                <div className={styles.actions}>
                  <span className={badgeClass(task.status)}>{task.status}</span>
                  {task.approval_status === "pending" && (
                    <>
                      <button className={styles.button} onClick={() => handleTaskAction(task.id, "approve")}>
                        Approve
                      </button>
                      <button
                        className={`${styles.button} ${styles.buttonDanger}`}
                        onClick={() => handleTaskAction(task.id, "reject")}
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {(task.approval_status === "approved" || task.approval_status === "not_required") &&
                    task.status === "pending" && (
                      <button
                        className={`${styles.button} ${styles.buttonPrimary}`}
                        onClick={() => handleTaskAction(task.id, "execute")}
                      >
                        Execute
                      </button>
                    )}
                  {changeRecords[task.id]?.validation_status === "failed" && (
                    <button
                      className={`${styles.button} ${styles.buttonDanger}`}
                      onClick={() => handleRollback(task.id)}
                    >
                      Roll back
                    </button>
                  )}
                </div>
                {changeRecords[task.id] && (
                  <span className={styles.rowMeta}>
                    last execution validation: {changeRecords[task.id].validation_status}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {activeTab === "integrations" && (
          <>
            <div className={styles.card}>
              <h2>Google Search Console</h2>
              <div className={styles.row}>
                <div className={styles.rowMain}>
                  <span>
                    {website.search_console_site_url
                      ? `Property: ${website.search_console_site_url}`
                      : "No property selected"}
                  </span>
                  <span className={styles.rowMeta}>
                    Connect at the organization level first, then select a property below.
                  </span>
                </div>
                <div className={styles.actions}>
                  <button className={styles.button} onClick={handleConnectGoogle}>
                    Connect Google
                  </button>
                  <button className={styles.button} onClick={handleLoadProperties}>
                    Load properties
                  </button>
                </div>
              </div>
              <div className={styles.actions}>
                <input
                  className={styles.input}
                  type="text"
                  placeholder="https://example.com/ or sc-domain:example.com"
                  value={sitePropertyInput}
                  onChange={(e) => setSitePropertyInput(e.target.value)}
                />
                <button className={styles.button} onClick={handleSelectProperty}>
                  Select property
                </button>
                <button className={styles.button} onClick={handleSyncSearchConsole}>
                  Sync now
                </button>
              </div>
              {searchPerformance && (
                <>
                  <p className={styles.rowMeta}>{searchPerformance.freshness_note}</p>
                  {searchPerformance.rows.slice(0, 10).map((row, i) => (
                    <div key={i} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>{row.query}</span>
                        <span className={styles.rowMeta}>{row.date}</span>
                      </div>
                      <span className={styles.rowMeta}>
                        {row.clicks} clicks · {row.impressions} impressions · pos {row.average_position.toFixed(1)}
                      </span>
                    </div>
                  ))}
                </>
              )}
            </div>

            <div className={styles.card}>
              <h2>WordPress connector</h2>
              {connections.filter((c) => c.connector_type === "wordpress").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Application username"
                    value={wpUsername}
                    onChange={(e) => setWpUsername(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="Application password"
                    value={wpPassword}
                    onChange={(e) => setWpPassword(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectWordPress}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "wordpress")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>WordPress</span>
                        <span className={styles.rowMeta}>
                          last verified {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <span className={badgeClass(connection.status)}>{connection.status}</span>
                        <button
                          className={`${styles.button} ${styles.buttonDanger}`}
                          onClick={handleDisconnectWordPress}
                        >
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>
          </>
        )}

        {activeTab === "reports" && (
          <div className={styles.card}>
            <h2>Weekly reports</h2>
            {reports.length === 0 && <p className={styles.empty}>No reports generated yet.</p>}
            {reports.map((report) => (
              <div key={report.id}>
                <p className={styles.rowMeta}>
                  {report.period_start} → {report.period_end}
                </p>
                <pre className={styles.jsonBlock}>{JSON.stringify(report.content_json, null, 2)}</pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
