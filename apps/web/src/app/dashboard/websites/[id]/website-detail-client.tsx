"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  ChangeRecord,
  CrawlJob,
  Ga4Metrics,
  Ga4Property,
  InternalLinkSuggestions,
  Opportunity,
  OpportunityProposal,
  Page,
  PageReport,
  QaSummary,
  Report,
  SEOFinding,
  SEOTask,
  SearchPerformance,
  SiteHealthScore,
  StrategySummary,
  Website,
  WebsiteConnection,
  WebsiteOverview,
  approveTask,
  connectGitHub,
  connectSanity,
  connectShopify,
  connectWebflow,
  connectWordPress,
  createProposal,
  createTasks,
  disconnectGa4,
  disconnectGitHub,
  disconnectSanity,
  disconnectShopify,
  disconnectWebflow,
  disconnectWordPress,
  executeTask,
  getGa4Metrics,
  getGa4Properties,
  getInternalLinkSuggestions,
  getMe,
  getPageReport,
  getQaSummary,
  getSearchPerformance,
  getSearchProperties,
  getWebsite,
  getWebsiteOverview,
  getWeeklyStrategy,
  listConnections,
  listCrawls,
  listFindings,
  listHealthScores,
  listOpportunities,
  listOrphanPages,
  listPages,
  listReports,
  listTasks,
  pauseWebsite,
  rejectTask,
  cancelTask,
  rollbackChange,
  rotateDeployWebhookSecret,
  selectGa4Property,
  selectSearchProperty,
  startGa4Connect,
  startGoogleConnect,
  syncGa4,
  syncSearchConsole,
  triggerCrawl,
  updateWebsiteSettings,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import ConfirmDialog from "@/components/ConfirmDialog";
import EmptyState from "@/components/EmptyState";
import { MetricGrid, type Metric as MetricCardMetric } from "@/components/MetricCard";
import StatusBadge from "@/components/StatusBadge";
import styles from "./detail.module.css";

function downloadCsv(filename: string, headers: string[], rows: (string | number)[][]) {
  const escapeCell = (value: string | number) => {
    const str = String(value);
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const csv = [headers, ...rows].map((row) => row.map(escapeCell).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

const TABS = [
  "overview",
  "crawls",
  "pages",
  "findings",
  "opportunities",
  "tasks",
  "integrations",
  "ai-agents",
  "reports",
] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  crawls: "Crawls",
  pages: "Pages",
  findings: "Findings",
  opportunities: "Opportunities",
  tasks: "Tasks",
  integrations: "Integrations",
  "ai-agents": "AI Agents",
  reports: "Reports",
};


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
  const [healthScores, setHealthScores] = useState<SiteHealthScore[]>([]);
  const [pages, setPages] = useState<Page[]>([]);
  const [findings, setFindings] = useState<SEOFinding[]>([]);
  const [findingsSearch, setFindingsSearch] = useState("");
  const [findingsSeverityFilter, setFindingsSeverityFilter] = useState("all");
  const [findingsStatusFilter, setFindingsStatusFilter] = useState("open");
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [showCompletedOpportunities, setShowCompletedOpportunities] = useState(false);
  const [proposals, setProposals] = useState<Record<string, OpportunityProposal>>({});
  const [tasks, setTasks] = useState<SEOTask[]>([]);
  const [connections, setConnections] = useState<WebsiteConnection[]>([]);
  const [searchPerformance, setSearchPerformance] = useState<SearchPerformance | null>(null);
  const [showSearchPerformance, setShowSearchPerformance] = useState(false);
  const [reports, setReports] = useState<Report[]>([]);
  const [changeRecords, setChangeRecords] = useState<Record<string, ChangeRecord>>({});
  const [overview, setOverview] = useState<WebsiteOverview | null>(null);
  const [expandedPageId, setExpandedPageId] = useState<string | null>(null);
  const [pageReports, setPageReports] = useState<Record<string, PageReport>>({});
  const [pageReportLoading, setPageReportLoading] = useState<string | null>(null);
  const [pageReportError, setPageReportError] = useState<string | null>(null);
  const [deployWebhookSecret, setDeployWebhookSecret] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<{ message: string; onConfirm: () => void } | null>(null);

  function requestConfirm(message: string, onConfirm: () => void) {
    setConfirmState({ message, onConfirm });
  }

  const [wpUsername, setWpUsername] = useState("");
  const [wpPassword, setWpPassword] = useState("");
  const [sitePropertyInput, setSitePropertyInput] = useState("");
  const [searchProperties, setSearchProperties] = useState<string[]>([]);

  const [shopifyDomain, setShopifyDomain] = useState("");
  const [shopifyToken, setShopifyToken] = useState("");
  const [webflowSiteId, setWebflowSiteId] = useState("");
  const [webflowToken, setWebflowToken] = useState("");
  const [sanityProjectId, setSanityProjectId] = useState("");
  const [sanityDataset, setSanityDataset] = useState("");
  const [sanityToken, setSanityToken] = useState("");
  const [githubOwner, setGithubOwner] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubBranch, setGithubBranch] = useState("main");
  const [githubToken, setGithubToken] = useState("");

  // Pre-fill the non-secret fields of a reconnect form from the most
  // recent connection of that type (connected or disconnected) -- the
  // backend never returns the encrypted credential itself (project ID
  // and dataset were right there, only the token has to be re-entered),
  // so there's no reason to make someone retype everything after a
  // disconnect just to reconnect the same site.
  useEffect(() => {
    const latestByType = new Map<string, WebsiteConnection>();
    for (const c of connections) {
      const existing = latestByType.get(c.connector_type);
      if (!existing || new Date(c.last_verified_at ?? 0) >= new Date(existing.last_verified_at ?? 0)) {
        latestByType.set(c.connector_type, c);
      }
    }

    // One-time sync from a freshly (re)fetched connections list into local
    // form state, each guarded so it only fires while that field is still
    // empty -- not the "external system" pattern the set-state-in-effect
    // rule assumes, so it's deliberately opted out below.
    const shopify = latestByType.get("shopify");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (shopify && !shopifyDomain) setShopifyDomain(String(shopify.config_json.shop_domain ?? ""));

    const webflow = latestByType.get("webflow");
    if (webflow && !webflowSiteId) setWebflowSiteId(String(webflow.config_json.site_id ?? ""));

    const sanity = latestByType.get("sanity");
    if (sanity && !sanityProjectId && !sanityDataset) {
      setSanityProjectId(String(sanity.config_json.project_id ?? ""));
      setSanityDataset(String(sanity.config_json.dataset ?? ""));
    }

    const github = latestByType.get("github");
    if (github && !githubOwner && !githubRepo) {
      setGithubOwner(String(github.config_json.owner ?? ""));
      setGithubRepo(String(github.config_json.repo ?? ""));
      setGithubBranch(String(github.config_json.base_branch ?? "main"));
    }
    // Only react to the connections list changing -- the emptiness
    // checks above are deliberately read, not depended on, so this
    // doesn't re-run (and fight the user's typing) on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connections]);

  const [ga4Properties, setGa4Properties] = useState<Ga4Property[]>([]);
  const [ga4PropertyInput, setGa4PropertyInput] = useState("");
  const [ga4Metrics, setGa4Metrics] = useState<Ga4Metrics | null>(null);
  const [showGa4Metrics, setShowGa4Metrics] = useState(false);

  const [strategySummary, setStrategySummary] = useState<StrategySummary | null>(null);
  const [orphanPages, setOrphanPages] = useState<Page[]>([]);
  const [linkSuggestions, setLinkSuggestions] = useState<Record<string, InternalLinkSuggestions>>({});
  const [qaSummaries, setQaSummaries] = useState<Record<string, QaSummary>>({});

  const pageUrlById = Object.fromEntries(pages.map((p) => [p.id, p.normalized_url]));

  const refreshAll = useCallback(async () => {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    const [site, crawlList, pageList, findingList, opportunityList, taskList, connectionList, reportList, healthScoreList] =
      await Promise.all([
        getWebsite(token, orgId, websiteId),
        listCrawls(token, orgId, websiteId),
        listPages(token, orgId, websiteId),
        listFindings(token, orgId, websiteId),
        listOpportunities(token, orgId, websiteId),
        listTasks(token, orgId, websiteId),
        listConnections(token, orgId, websiteId),
        listReports(token, orgId, websiteId),
        listHealthScores(token, orgId, websiteId),
      ]);
    setWebsite(site);
    if (site.search_console_site_url) setSitePropertyInput(site.search_console_site_url);
    if (site.ga4_property_id) setGa4PropertyInput(site.ga4_property_id);
    setCrawls(crawlList);
    setPages(pageList);
    setFindings(findingList);
    setOpportunities(opportunityList);
    setTasks(taskList);
    setConnections(connectionList);
    setReports(reportList);
    setHealthScores(healthScoreList);

    if (site.search_console_site_url) {
      try {
        setSearchPerformance(await getSearchPerformance(token, orgId, websiteId));
      } catch {
        // Search Console may not actually be connected yet; ignore.
      }
    }
    if (site.ga4_property_id) {
      try {
        setGa4Metrics(await getGa4Metrics(token, orgId, websiteId));
      } catch {
        // GA4 may not actually be connected yet; ignore.
      }
    }
    try {
      setOverview(await getWebsiteOverview(token, orgId, websiteId));
    } catch {
      // Best-effort: the overview tile row just stays hidden if this fails.
    }
  }, [websiteId]);

  async function toggleExpandedPage(pageId: string) {
    if (expandedPageId === pageId) {
      setExpandedPageId(null);
      return;
    }
    setExpandedPageId(pageId);
    if (pageReports[pageId]) return;
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setPageReportLoading(pageId);
    setPageReportError(null);
    try {
      const report = await getPageReport(token, orgId, websiteId, pageId);
      setPageReports((prev) => ({ ...prev, [pageId]: report }));
    } catch (err) {
      setPageReportError(err instanceof ApiError ? err.message : "Failed to load page report.");
    } finally {
      setPageReportLoading(null);
    }
  }

  // While a crawl is pending/running, poll its progress every few seconds
  // (the backend now commits pages_fetched/pages_requested as it goes --
  // app/crawler/orchestrator.py) instead of only finding out once the
  // whole crawl has finished.
  const settleAttemptsRef = useRef(0);
  useEffect(() => {
    const hasActiveCrawl = crawls.some((c) => c.status === "pending" || c.status === "running");

    if (hasActiveCrawl) {
      settleAttemptsRef.current = 0;
      const token = tokenRef.current;
      const orgId = orgIdRef.current;
      if (!token || !orgId) return;
      const interval = setInterval(async () => {
        try {
          setCrawls(await listCrawls(token, orgId, websiteId));
        } catch {
          // Transient polling error -- the next tick (or a manual refresh) will catch up.
        }
      }, 3000);
      return () => clearInterval(interval);
    }

    // The crawl itself just finished, but the auto-task pipeline
    // (app/opportunities/auto_pipeline.py) keeps writing tasks for a
    // while after that -- one refresh right away would often still show
    // stale "pending" tasks it hasn't gotten to yet. Refresh a few more
    // times on a backoff instead of only once, so the Tasks/Opportunities
    // tabs actually catch up with those trailing writes.
    const delays = [3000, 6000, 12000, 24000];
    if (settleAttemptsRef.current >= delays.length) return;
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    const timeout = setTimeout(async () => {
      settleAttemptsRef.current += 1;
      try {
        await refreshAll();
      } catch {
        // Transient polling error -- the next attempt (or a manual refresh) will catch up.
      }
    }, delays[settleAttemptsRef.current]);
    return () => clearTimeout(timeout);
  }, [crawls, websiteId, refreshAll]);

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
    requestConfirm(
      "Pause automation for this site? This immediately stops all automated writes and also stops crawling (scheduled and in-progress) until you resume.",
      async () => {
        setError(null);
        try {
          setWebsite(await pauseWebsite(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to pause website.");
        }
      }
    );
  }

  async function handleRotateWebhookSecret() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    const prompt = deployWebhookSecret
      ? "Rotate the deploy webhook secret? Whatever your CMS/CI pipeline has configured today will stop working until it's updated with the new one."
      : "Generate a deploy webhook secret for this website?";
    requestConfirm(prompt, async () => {
      setError(null);
      try {
        const result = await rotateDeployWebhookSecret(token, orgId, websiteId);
        setDeployWebhookSecret(result.secret);
      } catch (err) {
        setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to generate webhook secret.");
      }
    });
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

  async function handleTaskAction(taskId: string, action: "approve" | "reject" | "cancel" | "execute") {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    const confirmMessages: Partial<Record<"approve" | "reject" | "cancel" | "execute", string>> = {
      reject: "Reject this task? It will not be executed.",
      cancel: "Cancel this task? It will be discarded and cannot be executed afterward.",
      execute:
        "Execute this task now? This makes a real, bounded write to the connected site/CMS, validated right after.",
    };
    const run = async () => {
      setError(null);
      try {
        if (action === "approve") await approveTask(token, orgId, websiteId, taskId);
        else if (action === "reject") await rejectTask(token, orgId, websiteId, taskId);
        else if (action === "cancel") await cancelTask(token, orgId, websiteId, taskId);
        else {
          const changeRecord = await executeTask(token, orgId, websiteId, taskId);
          setChangeRecords((prev) => ({ ...prev, [taskId]: changeRecord }));
        }
        setTasks(await listTasks(token, orgId, websiteId));
      } catch (err) {
        setError(err instanceof ApiError ? `${err.status}: ${err.message}` : `Failed to ${action} task.`);
      }
    };
    const confirmMessage = confirmMessages[action];
    if (confirmMessage) requestConfirm(confirmMessage, run);
    else await run();
  }

  async function handleRollback(taskId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    const changeRecord = changeRecords[taskId];
    if (!token || !orgId || !changeRecord) return;
    requestConfirm(
      "Roll back this change? This writes the previous value back to the connected site/CMS.",
      async () => {
        setError(null);
        try {
          await rollbackChange(token, orgId, websiteId, changeRecord.id);
          setTasks(await listTasks(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to roll back.");
        }
      }
    );
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
    requestConfirm(
      "Disconnect WordPress? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectWordPress(token, orgId, websiteId);
          setConnections(await listConnections(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect WordPress.");
        }
      }
    );
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
      setSearchProperties(site_urls);
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

  async function handleConnectShopify() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await connectShopify(token, orgId, websiteId, shopifyDomain, shopifyToken);
      setShopifyDomain("");
      setShopifyToken("");
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to connect Shopify.");
    }
  }

  async function handleDisconnectShopify() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    requestConfirm(
      "Disconnect Shopify? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectShopify(token, orgId, websiteId);
          setConnections(await listConnections(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect Shopify.");
        }
      }
    );
  }

  async function handleConnectWebflow() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await connectWebflow(token, orgId, websiteId, webflowSiteId, webflowToken);
      setWebflowSiteId("");
      setWebflowToken("");
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to connect Webflow.");
    }
  }

  async function handleDisconnectWebflow() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    requestConfirm(
      "Disconnect Webflow? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectWebflow(token, orgId, websiteId);
          setConnections(await listConnections(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect Webflow.");
        }
      }
    );
  }

  async function handleConnectSanity() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await connectSanity(token, orgId, websiteId, sanityProjectId, sanityDataset, sanityToken);
      setSanityProjectId("");
      setSanityDataset("");
      setSanityToken("");
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to connect Sanity.");
    }
  }

  async function handleDisconnectSanity() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    requestConfirm(
      "Disconnect Sanity? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectSanity(token, orgId, websiteId);
          setConnections(await listConnections(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect Sanity.");
        }
      }
    );
  }

  async function handleConnectGitHub() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await connectGitHub(token, orgId, websiteId, githubOwner, githubRepo, githubBranch, githubToken);
      setGithubOwner("");
      setGithubRepo("");
      setGithubToken("");
      setConnections(await listConnections(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to connect GitHub.");
    }
  }

  async function handleDisconnectGitHub() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    requestConfirm(
      "Disconnect GitHub? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectGitHub(token, orgId, websiteId);
          setConnections(await listConnections(token, orgId, websiteId));
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect GitHub.");
        }
      }
    );
  }

  async function handleConnectGa4() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const { authorization_url } = await startGa4Connect(token, orgId);
      window.location.href = authorization_url;
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to start GA4 connect.");
    }
  }

  async function handleDisconnectGa4() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    requestConfirm(
      "Disconnect Google Analytics (GA4)? RankPilot will no longer be able to apply approved changes to this site until you reconnect.",
      async () => {
        setError(null);
        try {
          await disconnectGa4(token, orgId);
          setGa4Properties([]);
          setGa4Metrics(null);
        } catch (err) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to disconnect GA4.");
        }
      }
    );
  }

  async function handleLoadGa4Properties() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const { properties } = await getGa4Properties(token, orgId, websiteId);
      setGa4Properties(properties);
      if (properties.length > 0) setGa4PropertyInput(properties[0].property_id);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to load GA4 properties.");
    }
  }

  async function handleSelectGa4Property() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId || !ga4PropertyInput) return;
    setError(null);
    try {
      setWebsite(await selectGa4Property(token, orgId, websiteId, ga4PropertyInput));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to select GA4 property.");
    }
  }

  async function handleSyncGa4() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      await syncGa4(token, orgId, websiteId);
      setGa4Metrics(await getGa4Metrics(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to sync GA4.");
    }
  }

  async function handleGetWeeklyStrategy() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      setStrategySummary(await getWeeklyStrategy(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to generate strategy.");
    }
  }

  async function handleLoadOrphanPages() {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      setOrphanPages(await listOrphanPages(token, orgId, websiteId));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to load orphan pages.");
    }
  }

  async function handleGetLinkSuggestions(pageId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    if (!token || !orgId) return;
    setError(null);
    try {
      const suggestions = await getInternalLinkSuggestions(token, orgId, websiteId, pageId);
      setLinkSuggestions((prev) => ({ ...prev, [pageId]: suggestions }));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to get link suggestions.");
    }
  }

  async function handleGetQaSummary(taskId: string) {
    const token = tokenRef.current;
    const orgId = orgIdRef.current;
    const changeRecord = changeRecords[taskId];
    if (!token || !orgId || !changeRecord) return;
    setError(null);
    try {
      const summary = await getQaSummary(token, orgId, websiteId, changeRecord.id);
      setQaSummaries((prev) => ({ ...prev, [taskId]: summary }));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : "Failed to get QA summary.");
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
          {error ? <p className={styles.error} role="alert">{error}</p> : <p>Website not found.</p>}
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
          <div>
            <h1>{website.display_name}</h1>
            <div className={styles.headerMeta}>
              <span>{website.canonical_url}</span>
              <StatusBadge value={website.verification_status} />
              <StatusBadge value={website.status} />
              <span>
                {(() => {
                  const lastCrawl = [...crawls].sort(
                    (a, b) => new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime()
                  )[0];
                  if (!lastCrawl) return "No crawls yet";
                  if (!lastCrawl.completed_at) return `Last crawl: ${lastCrawl.status}`;
                  return `Last crawl: ${new Date(lastCrawl.completed_at).toLocaleString()}`;
                })()}
              </span>
            </div>
          </div>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}

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
          <>
            {(() => {
              const hostCounts = new Map<string, number>();
              for (const page of pages) {
                try {
                  const host = new URL(page.normalized_url).hostname.toLowerCase();
                  hostCounts.set(host, (hostCounts.get(host) ?? 0) + 1);
                } catch {
                  // malformed URL -- skip, this check is best-effort
                }
              }
              if (hostCounts.size <= 1) return null;
              const breakdown = Array.from(hostCounts.entries())
                .sort((a, b) => b[1] - a[1])
                .map(([host, count]) => `${host} (${count} page${count === 1 ? "" : "s"})`)
                .join(", ");
              let canonicalHost = "your canonical domain";
              try {
                if (website) canonicalHost = new URL(website.canonical_url).hostname.toLowerCase();
              } catch {
                // leave fallback
              }
              return (
                <div className={`${styles.card} ${styles.healthAlert}`}>
                  <h2>Technical health check</h2>
                  <p className={styles.rowMeta}>
                    Crawled pages span {hostCounts.size} different hostnames: {breakdown}. Search engines
                    treat each hostname as a separate site, which splits ranking signals and is the usual
                    cause of duplicate-title, duplicate-meta-description, and canonical-mismatch findings
                    below.
                  </p>
                  <p className={styles.rowMeta}>
                    Fix: add a server-level 301 redirect from the other hostname(s) to{" "}
                    <strong>{canonicalHost}</strong>, and make sure the site&apos;s sitemap and canonical
                    tags all use that same hostname. Then run a crawl again.
                  </p>
                </div>
              );
            })()}

            {healthScores.length > 0 && (
              <div className={styles.card}>
                <h2>SEO Health Score</h2>
                {(() => {
                  const current = healthScores[0];
                  const previous = healthScores[1];
                  const delta =
                    current.overall_score !== null && previous?.overall_score != null
                      ? current.overall_score - previous.overall_score
                      : null;
                  const pendingApprovals = tasks.filter((t) => t.approval_status === "pending").length;
                  const autoFixed = tasks.filter((t) => t.status === "completed").length;
                  const fmt = (v: number | null) => (v === null ? "Not measured" : Math.round(v));
                  return (
                    <>
                      <div className={styles.healthScoreHeader}>
                        <span className={styles.healthScoreValue}>
                          {current.overall_score !== null ? Math.round(current.overall_score) : "—"}
                        </span>
                        <span className={styles.rowMeta}>/ 100</span>
                        {delta !== null && (
                          <span className={delta >= 0 ? styles.scoreUp : styles.scoreDown}>
                            {delta >= 0 ? "▲" : "▼"} {Math.abs(Math.round(delta))} vs previous crawl
                          </span>
                        )}
                      </div>
                      <MetricGrid
                        metrics={[
                          {
                            label: "Critical issues",
                            value: current.critical_count,
                            attention: current.critical_count > 0,
                          },
                          { label: "Warnings", value: current.warning_count },
                          { label: "Passed checks", value: current.passed_count },
                          { label: "Auto-fixed issues", value: autoFixed },
                          { label: "Pending approvals", value: pendingApprovals, attention: pendingApprovals > 0 },
                          { label: "Technical score", value: fmt(current.technical_score) },
                          { label: "On-page score", value: fmt(current.on_page_score) },
                          { label: "Content score", value: fmt(current.content_score) },
                          { label: "Performance score", value: fmt(current.performance_score) },
                        ]}
                      />
                      {healthScores.length > 1 && (
                        <div>
                          <span className={styles.rowMeta}>Score history (most recent first)</span>
                          <div className={styles.scoreHistoryRow}>
                            {healthScores.slice(0, 10).map((s) => (
                              <span
                                key={s.id}
                                className={styles.scoreHistoryPoint}
                                title={new Date(s.created_at).toLocaleString()}
                              >
                                {s.overall_score !== null ? Math.round(s.overall_score) : "–"}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            )}

            <div className={styles.card}>
              <h2>Site health</h2>
              <MetricGrid
                metrics={[
                  { label: "Pages crawled", value: pages.length },
                  ...(overview?.pages_indexed !== null && overview?.pages_indexed !== undefined
                    ? [{ label: "Pages indexed by Google", value: overview.pages_indexed }]
                    : []),
                  {
                    label: "Open findings",
                    value: findings.filter((f) => f.status === "open").length,
                    attention: findings.some((f) => f.status === "open" && f.severity === "critical"),
                  },
                  { label: "Open opportunities", value: opportunities.filter((o) => o.status === "open").length },
                  { label: "Completed tasks", value: tasks.filter((t) => t.status === "completed").length },
                ]}
              />
              {(() => {
                const criticalOpen = findings.filter((f) => f.status === "open" && f.severity === "critical").length;
                const openFindings = findings.filter((f) => f.status === "open").length;
                const openOpportunities = opportunities.filter((o) => o.status === "open").length;
                const pendingTasks = tasks.filter(
                  (t) => t.status === "pending" && t.approval_status === "pending"
                ).length;
                let message = "This site is caught up — nothing needs attention right now.";
                let actionTab: Tab | null = null;
                if (crawls.length === 0) {
                  message = "No crawl has run yet. Run one to start finding issues.";
                  actionTab = "crawls";
                } else if (criticalOpen > 0) {
                  message = `${criticalOpen} critical finding${criticalOpen === 1 ? "" : "s"} need${criticalOpen === 1 ? "s" : ""} review.`;
                  actionTab = "findings";
                } else if (openFindings > 0) {
                  message = `${openFindings} open finding${openFindings === 1 ? "" : "s"} to review.`;
                  actionTab = "findings";
                } else if (openOpportunities > 0) {
                  message = `${openOpportunities} open opportunit${openOpportunities === 1 ? "y" : "ies"} to review.`;
                  actionTab = "opportunities";
                } else if (pendingTasks > 0) {
                  message = `${pendingTasks} task${pendingTasks === 1 ? "" : "s"} awaiting approval.`;
                  actionTab = "tasks";
                }
                return (
                  <div className={styles.row}>
                    <div className={styles.rowMain}>
                      <span>Recommended next action</span>
                      <span className={styles.rowMeta}>{message}</span>
                    </div>
                    {actionTab && (
                      <button className={styles.button} onClick={() => setActiveTab(actionTab as Tab)}>
                        Go
                      </button>
                    )}
                  </div>
                );
              })()}
            </div>

            <div className={styles.card}>
              <h2>Settings</h2>
            <div className={styles.row}>
              <div className={styles.rowMain}>
                <span>Website status</span>
                <span className={styles.rowMeta}>
                  Pausing immediately stops all automated writes and also stops crawling (scheduled and
                  in-progress) until you resume.
                </span>
              </div>
              <div className={styles.actions}>
                <StatusBadge value={website.status} />
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
          </>
        )}

        {activeTab === "crawls" && (
          <div className={styles.card}>
            <h2>Crawls</h2>
            <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleTriggerCrawl}>
              Run a crawl now
            </button>
            {crawls.length === 0 && (
              <EmptyState title="No crawls yet" description="Run the first crawl to start discovering pages and issues." />
            )}
            {crawls.map((crawl) => {
              const isActive = crawl.status === "pending" || crawl.status === "running";
              const budget = website?.crawl_budget || 1;
              const percent = Math.min(100, Math.round((crawl.pages_fetched / budget) * 100));
              return (
                <div key={crawl.id} className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div className={styles.row} style={{ border: "none", padding: 0 }}>
                    <div className={styles.rowMain}>
                      <span>{crawl.trigger} crawl</span>
                      <span className={styles.rowMeta}>
                        {crawl.pages_fetched}/{crawl.pages_requested} pages fetched
                        {crawl.error_summary ? ` — ${crawl.error_summary}` : ""}
                      </span>
                      <span className={styles.rowMeta}>
                        {crawl.started_at ? `Started ${new Date(crawl.started_at).toLocaleString()}` : "Not started yet"}
                        {crawl.completed_at ? ` · Completed ${new Date(crawl.completed_at).toLocaleString()}` : ""}
                      </span>
                    </div>
                    <StatusBadge value={crawl.status} />
                  </div>
                  {isActive && (
                    <div className={styles.progressTrack}>
                      <div className={styles.progressFill} style={{ width: `${percent}%` }} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {activeTab === "pages" && (
          <div className={styles.card}>
            <h2>Pages</h2>
            {pages.length === 0 ? (
              <EmptyState title="No pages yet" description="Run a crawl first — pages appear once they've been fetched." />
            ) : (
              pages.map((page) => {
                const expanded = expandedPageId === page.id;
                const report = pageReports[page.id];
                const findingCount = findings.filter((f) => f.page_id === page.id && f.status === "open").length;
                return (
                  <div key={page.id} className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                    <div className={styles.row} style={{ border: "none", padding: 0 }}>
                      <div className={styles.rowMain}>
                        <span>{page.normalized_url}</span>
                        <span className={styles.rowMeta}>
                          {page.last_status_code ?? "—"} · {page.indexability_state}
                          {findingCount > 0 ? ` · ${findingCount} open finding${findingCount === 1 ? "" : "s"}` : ""}
                        </span>
                      </div>
                      <button className={styles.button} onClick={() => toggleExpandedPage(page.id)}>
                        {expanded ? "Hide report" : "View report"}
                      </button>
                    </div>

                    {expanded && (
                      <div className={styles.rowMeta} style={{ marginTop: "0.75rem" }}>
                        {pageReportLoading === page.id && <p>Loading report…</p>}
                        {pageReportError && pageReportLoading !== page.id && <p>{pageReportError}</p>}
                        {report && (
                          <>
                            <h3>Snapshot</h3>
                            {report.latest_snapshot ? (
                              <>
                                <p>Title: {report.latest_snapshot.title ?? "Missing"}</p>
                                <p>Meta description: {report.latest_snapshot.meta_description ?? "Missing"}</p>
                                <p>Canonical: {report.latest_snapshot.canonical_url ?? "Missing"}</p>
                                <p>Viewport: {report.latest_snapshot.viewport_content ?? "Missing"}</p>
                                <p>Word count: {report.latest_snapshot.word_count}</p>
                              </>
                            ) : (
                              <p>No snapshot yet — this page hasn&apos;t been crawled.</p>
                            )}

                            <h3>Images ({report.images.length})</h3>
                            {report.images.length === 0 ? (
                              <p>No images on this page.</p>
                            ) : (
                              report.images.map((img, i) => (
                                <p key={i}>
                                  {img.image_src ?? "(no src)"} — {img.has_alt ? "has alt text" : "missing alt text"}
                                  {img.image_status !== "ok" ? ` · ${img.image_status}` : ""}
                                </p>
                              ))
                            )}

                            <h3>Performance</h3>
                            {report.performance ? (
                              <p>
                                Lab score:{" "}
                                {report.performance.lab_performance_score !== null
                                  ? Math.round(report.performance.lab_performance_score)
                                  : "Not measured"}
                                {report.performance.field_lcp_ms !== null
                                  ? ` · Field LCP: ${Math.round(report.performance.field_lcp_ms)}ms`
                                  : ""}
                              </p>
                            ) : (
                              <p>Not measured yet (connect PageSpeed Insights).</p>
                            )}

                            <h3>Google indexing status</h3>
                            {report.indexing_status ? (
                              <>
                                <p>Verdict: {report.indexing_status.verdict}</p>
                                {report.indexing_status.coverage_state && (
                                  <p>Coverage: {report.indexing_status.coverage_state}</p>
                                )}
                                {report.indexing_status.google_canonical_url &&
                                  report.indexing_status.user_canonical_url &&
                                  report.indexing_status.google_canonical_url !==
                                    report.indexing_status.user_canonical_url && (
                                    <p>
                                      Google chose a different canonical:{" "}
                                      {report.indexing_status.google_canonical_url}
                                    </p>
                                  )}
                              </>
                            ) : (
                              <p>Not measured yet (connect Google Search Console).</p>
                            )}

                            <h3>Fix history ({report.change_history.length})</h3>
                            {report.change_history.length === 0 ? (
                              <p>No automated fixes have been executed on this page.</p>
                            ) : (
                              report.change_history.map((change) => (
                                <p key={change.id}>
                                  {new Date(change.executed_at).toLocaleString()} —{" "}
                                  {change.validation_status}
                                </p>
                              ))
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "findings" && (
          <div className={styles.card}>
            <h2>Findings</h2>
            {findings.length === 0 ? (
              <EmptyState title="No findings yet" description="Run a crawl first — findings appear once pages have been fetched and checked." />
            ) : (
              <>
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Search by URL or rule code"
                    aria-label="Search by URL or rule code"
                    value={findingsSearch}
                    onChange={(e) => setFindingsSearch(e.target.value)}
                  />
                  <select
                    className={styles.input}
                    aria-label="Filter by severity"
                    value={findingsSeverityFilter}
                    onChange={(e) => setFindingsSeverityFilter(e.target.value)}
                  >
                    <option value="all">All severities</option>
                    <option value="critical">Critical</option>
                    <option value="warning">Warning</option>
                    <option value="info">Info</option>
                  </select>
                  <select
                    className={styles.input}
                    aria-label="Filter by status"
                    value={findingsStatusFilter}
                    onChange={(e) => setFindingsStatusFilter(e.target.value)}
                  >
                    <option value="all">All statuses</option>
                    <option value="open">Open</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </div>
                {(() => {
                  const q = findingsSearch.trim().toLowerCase();
                  const filtered = findings.filter((f) => {
                    if (findingsSeverityFilter !== "all" && f.severity !== findingsSeverityFilter) return false;
                    if (findingsStatusFilter !== "all" && f.status !== findingsStatusFilter) return false;
                    if (!q) return true;
                    const url = f.page_id ? pageUrlById[f.page_id] ?? f.page_id : "site-wide";
                    return f.rule_code.toLowerCase().includes(q) || url.toLowerCase().includes(q);
                  });
                  return (
                    <>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          onClick={() =>
                            downloadCsv(
                              `${website?.hostname ?? "website"}-findings.csv`,
                              ["rule_code", "url", "severity", "status"],
                              filtered.map((f) => [
                                f.rule_code,
                                f.page_id ? pageUrlById[f.page_id] ?? f.page_id : "site-wide",
                                f.severity,
                                f.status,
                              ])
                            )
                          }
                        >
                          Download CSV ({filtered.length})
                        </button>
                      </div>
                      {filtered.length === 0 ? (
                        <EmptyState title="No findings match these filters" description="Try a different search term or widen the severity/status filters." />
                      ) : (
                        filtered.map((finding) => (
                          <div key={finding.id} className={styles.row}>
                            <div className={styles.rowMain}>
                              <span>{finding.rule_code}</span>
                              <span className={styles.rowMeta}>
                                {finding.page_id ? pageUrlById[finding.page_id] ?? finding.page_id : "site-wide"}
                              </span>
                            </div>
                            <div className={styles.actions}>
                              <StatusBadge value={finding.severity} />
                              <StatusBadge value={finding.status} />
                            </div>
                          </div>
                        ))
                      )}
                    </>
                  );
                })()}
              </>
            )}
          </div>
        )}

        {activeTab === "opportunities" && (
          <div className={styles.card}>
            <h2>Opportunities</h2>
            {opportunities.length > 0 && (
              <div className={styles.actions} style={{ alignItems: "center" }}>
                <label className={styles.rowMeta} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <input
                    type="checkbox"
                    checked={showCompletedOpportunities}
                    onChange={(e) => setShowCompletedOpportunities(e.target.checked)}
                  />
                  Show completed/resolved ({opportunities.filter((o) => o.status !== "open").length})
                </label>
                <button
                  type="button"
                  onClick={() => {
                    const visible = opportunities.filter((o) => showCompletedOpportunities || o.status === "open");
                    downloadCsv(
                      `${website?.hostname ?? "website"}-opportunities.csv`,
                      ["title", "category", "url", "status", "impact", "confidence", "effort", "risk_tier", "score", "rationale"],
                      visible.map((o) => [
                        o.title,
                        o.category,
                        o.page_id ? pageUrlById[o.page_id] ?? o.page_id : "site-wide",
                        o.status,
                        o.impact_estimate,
                        o.confidence,
                        o.effort_estimate,
                        o.risk_tier,
                        o.score,
                        o.rationale,
                      ])
                    );
                  }}
                >
                  Download CSV
                </button>
              </div>
            )}
            {opportunities.length === 0 && (
              <EmptyState title="No opportunities yet" description="Run a crawl first — opportunities are derived from open findings and connected search data." />
            )}
            {opportunities.length > 0 &&
              opportunities.filter((o) => showCompletedOpportunities || o.status === "open").length === 0 && (
                <EmptyState title="No open opportunities right now" description="Nice work — everything currently detected has been resolved or completed." />
              )}
            {opportunities
              .filter((opportunity) => showCompletedOpportunities || opportunity.status === "open")
              .map((opportunity) => (
              <div key={opportunity.id} className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className={styles.row} style={{ border: "none", padding: 0 }}>
                  <div className={styles.rowMain}>
                    <span>{opportunity.title}</span>
                    <span className={styles.rowMeta}>
                      {opportunity.page_id ? pageUrlById[opportunity.page_id] ?? opportunity.page_id : "Site-wide"}
                    </span>
                    <span className={styles.rowMeta}>
                      impact {opportunity.impact_estimate.toFixed(2)} · confidence{" "}
                      {opportunity.confidence.toFixed(2)} · effort {opportunity.effort_estimate.toFixed(2)} · risk
                      tier {opportunity.risk_tier} · score {opportunity.score.toFixed(2)}
                    </span>
                    <span className={styles.rowMeta}>{opportunity.rationale}</span>
                  </div>
                  <div className={styles.actions}>
                    <StatusBadge value={opportunity.category} tone="info" />
                    <StatusBadge value={opportunity.status} />
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
            {tasks.length > 0 && (
              <div className={styles.actions}>
                <button
                  type="button"
                  onClick={() =>
                    downloadCsv(
                      `${website?.hostname ?? "website"}-tasks.csv`,
                      ["task_type", "risk_tier", "approval_status", "status"],
                      tasks.map((t) => [t.task_type, t.risk_tier, t.approval_status, t.status])
                    )
                  }
                >
                  Download CSV ({tasks.length})
                </button>
              </div>
            )}
            {tasks.length === 0 && (
              <EmptyState title="No tasks yet" description="A task is created once you accept an AI proposal for an opportunity." />
            )}
            {(() => {
              const renderTaskRow = (task: SEOTask) => (
                <div key={task.id} className={styles.row}>
                  <div className={styles.rowMain}>
                    <span>{task.task_type}</span>
                    <span className={styles.rowMeta}>risk tier {task.risk_tier}</span>
                  </div>
                  <div className={styles.actions}>
                    <StatusBadge value={task.approval_status} label={`approval: ${task.approval_status}`} />
                    <StatusBadge value={task.status} />
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
                        <>
                          <button
                            className={`${styles.button} ${styles.buttonPrimary}`}
                            onClick={() => handleTaskAction(task.id, "execute")}
                          >
                            Execute
                          </button>
                          <button
                            className={`${styles.button} ${styles.buttonDanger}`}
                            onClick={() => handleTaskAction(task.id, "cancel")}
                          >
                            Cancel
                          </button>
                        </>
                      )}
                    {changeRecords[task.id]?.validation_status === "failed" && (
                      <button
                        className={`${styles.button} ${styles.buttonDanger}`}
                        onClick={() => handleRollback(task.id)}
                      >
                        Roll back
                      </button>
                    )}
                    {changeRecords[task.id] && !qaSummaries[task.id] && (
                      <button className={styles.button} onClick={() => handleGetQaSummary(task.id)}>
                        Get QA summary
                      </button>
                    )}
                  </div>
                  {changeRecords[task.id] && (
                    <span className={styles.rowMeta}>
                      last execution validation: {changeRecords[task.id].validation_status}
                    </span>
                  )}
                  {qaSummaries[task.id] && (
                    <div className={styles.proposalBox}>
                      <span>{qaSummaries[task.id].summary}</span>
                      <span className={styles.rowMeta}>
                        validation status: {qaSummaries[task.id].validation_status}
                      </span>
                    </div>
                  )}
                </div>
              );

              const groups: { key: string; label: string; items: SEOTask[] }[] = [
                {
                  key: "needs_approval",
                  label: "Needs your approval",
                  items: tasks.filter((t) => t.approval_status === "pending"),
                },
                {
                  key: "ready",
                  label: "Ready to execute",
                  items: tasks.filter((t) => t.approval_status !== "pending" && t.status === "pending"),
                },
                { key: "executing", label: "Executing", items: tasks.filter((t) => t.status === "executing") },
                { key: "completed", label: "Completed", items: tasks.filter((t) => t.status === "completed") },
                { key: "failed", label: "Failed", items: tasks.filter((t) => t.status === "failed") },
                {
                  key: "rejected",
                  label: "Rejected / cancelled",
                  items: tasks.filter((t) => t.status === "rejected"),
                },
              ];

              return groups
                .filter((group) => group.items.length > 0)
                .map((group) => (
                  <div key={group.key} className={styles.taskGroup}>
                    <h3 className={styles.taskGroupHeading}>
                      {group.label} ({group.items.length})
                    </h3>
                    {group.items.map(renderTaskRow)}
                  </div>
                ));
            })()}
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
                {searchProperties.length > 0 ? (
                  <select
                    className={styles.input}
                    aria-label="Search Console property"
                    value={sitePropertyInput}
                    onChange={(e) => setSitePropertyInput(e.target.value)}
                  >
                    {searchProperties.map((url) => (
                      <option key={url} value={url}>
                        {url}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="https://example.com/ or sc-domain:example.com"
                    aria-label="https://example.com/ or sc-domain:example.com"
                    value={sitePropertyInput}
                    onChange={(e) => setSitePropertyInput(e.target.value)}
                  />
                )}
                <button className={styles.button} onClick={handleSelectProperty}>
                  Select property
                </button>
                <button className={styles.button} onClick={handleSyncSearchConsole}>
                  Sync now
                </button>
              </div>
              {searchPerformance && (
                <>
                  <button
                    className={styles.button}
                    onClick={() => setShowSearchPerformance((v) => !v)}
                    style={{ marginTop: "0.75rem" }}
                  >
                    {showSearchPerformance ? "Hide" : "Show"} synced data ({searchPerformance.rows.length} rows)
                  </button>
                  {showSearchPerformance && (
                    <>
                      <p className={styles.rowMeta}>{searchPerformance.freshness_note}</p>
                      {searchPerformance.rows.slice(0, 10).map((row, i) => (
                        <div key={i} className={styles.row}>
                          <div className={styles.rowMain}>
                            <span>{row.query}</span>
                            <span className={styles.rowMeta}>{row.date}</span>
                          </div>
                          <span className={styles.rowMeta}>
                            {row.clicks} clicks · {row.impressions} impressions · pos{" "}
                            {row.average_position.toFixed(1)}
                          </span>
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </div>

            <div className={styles.card}>
              <h2>WordPress connector</h2>
              {connections.filter((c) => c.connector_type === "wordpress" && c.status === "connected").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Application username"
                    aria-label="Application username"
                    value={wpUsername}
                    onChange={(e) => setWpUsername(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="Application password"
                    aria-label="Application password"
                    value={wpPassword}
                    onChange={(e) => setWpPassword(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectWordPress}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "wordpress" && c.status === "connected")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>WordPress</span>
                        <span className={styles.rowMeta}>
                          last verified {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <StatusBadge value={connection.status} />
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

            <div className={styles.card}>
              <h2>Google Analytics (GA4)</h2>
              <div className={styles.row}>
                <div className={styles.rowMain}>
                  <span>{website.ga4_property_id ? `Property: ${website.ga4_property_id}` : "No property selected"}</span>
                  <span className={styles.rowMeta}>
                    Connect at the organization level first, then select a property below.
                  </span>
                </div>
                <div className={styles.actions}>
                  <button className={styles.button} onClick={handleConnectGa4}>
                    Connect Google
                  </button>
                  <button className={styles.button} onClick={handleLoadGa4Properties}>
                    Load properties
                  </button>
                  <button className={`${styles.button} ${styles.buttonDanger}`} onClick={handleDisconnectGa4}>
                    Disconnect
                  </button>
                </div>
              </div>
              <div className={styles.actions}>
                {ga4Properties.length > 0 ? (
                  <select
                    className={styles.input}
                    aria-label="GA4 property"
                    value={ga4PropertyInput}
                    onChange={(e) => setGa4PropertyInput(e.target.value)}
                  >
                    {ga4Properties.map((p) => (
                      <option key={p.property_id} value={p.property_id}>
                        {p.display_name ? `${p.display_name} (${p.property_id})` : p.property_id}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="properties/123456789"
                    aria-label="properties/123456789"
                    value={ga4PropertyInput}
                    onChange={(e) => setGa4PropertyInput(e.target.value)}
                  />
                )}
                <button className={styles.button} onClick={handleSelectGa4Property}>
                  Select property
                </button>
                <button className={styles.button} onClick={handleSyncGa4}>
                  Sync now
                </button>
              </div>
              {ga4Metrics && (
                <>
                  <button
                    className={styles.button}
                    onClick={() => setShowGa4Metrics((v) => !v)}
                    style={{ marginTop: "0.75rem" }}
                  >
                    {showGa4Metrics ? "Hide" : "Show"} synced data ({ga4Metrics.rows.length} rows)
                  </button>
                  {showGa4Metrics && (
                    <>
                      <p className={styles.rowMeta}>{ga4Metrics.freshness_note}</p>
                      {ga4Metrics.rows.slice(0, 10).map((row, i) => (
                        <div key={i} className={styles.row}>
                          <div className={styles.rowMain}>
                            <span>{row.date}</span>
                          </div>
                          <span className={styles.rowMeta}>
                            {row.sessions} sessions · {row.total_users} users · {row.conversions} conversions
                          </span>
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </div>

            <div className={styles.card}>
              <h2>Shopify connector</h2>
              {connections.filter((c) => c.connector_type === "shopify" && c.status === "connected").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="shop.myshopify.com"
                    aria-label="shop.myshopify.com"
                    value={shopifyDomain}
                    onChange={(e) => setShopifyDomain(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="Admin API access token"
                    aria-label="Admin API access token"
                    value={shopifyToken}
                    onChange={(e) => setShopifyToken(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectShopify}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "shopify" && c.status === "connected")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>Shopify</span>
                        <span className={styles.rowMeta}>
                          {String(connection.config_json.shop_domain ?? "")} · last verified{" "}
                          {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <StatusBadge value={connection.status} />
                        <button className={`${styles.button} ${styles.buttonDanger}`} onClick={handleDisconnectShopify}>
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>

            <div className={styles.card}>
              <h2>Webflow connector</h2>
              {connections.filter((c) => c.connector_type === "webflow" && c.status === "connected").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Webflow site ID"
                    aria-label="Webflow site ID"
                    value={webflowSiteId}
                    onChange={(e) => setWebflowSiteId(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="Site API token"
                    aria-label="Site API token"
                    value={webflowToken}
                    onChange={(e) => setWebflowToken(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectWebflow}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "webflow" && c.status === "connected")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>Webflow</span>
                        <span className={styles.rowMeta}>
                          site {String(connection.config_json.site_id ?? "")} · last verified{" "}
                          {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <StatusBadge value={connection.status} />
                        <button className={`${styles.button} ${styles.buttonDanger}`} onClick={handleDisconnectWebflow}>
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>

            <div className={styles.card}>
              <h2>Sanity CMS connector</h2>
              <p className={styles.rowMeta}>
                Reads and patches mapped SEO fields (title/meta description) on this site&apos;s Sanity
                documents. Only touches explicitly mapped fields, never slugs or publishing.
              </p>
              {connections.filter((c) => c.connector_type === "sanity" && c.status === "connected").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Sanity project ID"
                    aria-label="Sanity project ID"
                    value={sanityProjectId}
                    onChange={(e) => setSanityProjectId(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Dataset (e.g. production)"
                    aria-label="Dataset (e.g. production)"
                    value={sanityDataset}
                    onChange={(e) => setSanityDataset(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="API token"
                    aria-label="API token"
                    value={sanityToken}
                    onChange={(e) => setSanityToken(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectSanity}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "sanity" && c.status === "connected")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>Sanity</span>
                        <span className={styles.rowMeta}>
                          project {String(connection.config_json.project_id ?? "")} / dataset{" "}
                          {String(connection.config_json.dataset ?? "")} · last verified{" "}
                          {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <StatusBadge value={connection.status} />
                        <button className={`${styles.button} ${styles.buttonDanger}`} onClick={handleDisconnectSanity}>
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>

            <div className={styles.card}>
              <h2>GitHub connector (custom-code sites)</h2>
              <p className={styles.rowMeta}>
                For sites with no live write API, changes are proposed as a pull request for a human to
                review and merge — RankPilot AI never merges or deploys automatically.
              </p>
              {connections.filter((c) => c.connector_type === "github" && c.status === "connected").length === 0 ? (
                <div className={styles.actions}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="owner"
                    aria-label="owner"
                    value={githubOwner}
                    onChange={(e) => setGithubOwner(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="repo"
                    aria-label="repo"
                    value={githubRepo}
                    onChange={(e) => setGithubRepo(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="base branch"
                    aria-label="base branch"
                    value={githubBranch}
                    onChange={(e) => setGithubBranch(e.target.value)}
                  />
                  <input
                    className={styles.input}
                    type="password"
                    placeholder="Personal access token"
                    aria-label="Personal access token"
                    value={githubToken}
                    onChange={(e) => setGithubToken(e.target.value)}
                  />
                  <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleConnectGitHub}>
                    Connect
                  </button>
                </div>
              ) : (
                connections
                  .filter((c) => c.connector_type === "github" && c.status === "connected")
                  .map((connection) => (
                    <div key={connection.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span>GitHub</span>
                        <span className={styles.rowMeta}>
                          {String(connection.config_json.owner ?? "")}/{String(connection.config_json.repo ?? "")} (
                          {String(connection.config_json.base_branch ?? "")}) · last verified{" "}
                          {connection.last_verified_at ?? "never"}
                        </span>
                      </div>
                      <div className={styles.actions}>
                        <StatusBadge value={connection.status} />
                        <button className={`${styles.button} ${styles.buttonDanger}`} onClick={handleDisconnectGitHub}>
                          Disconnect
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>

            <div className={styles.card}>
              <h2>Deploy webhook</h2>
              <p className={styles.rowMeta}>
                Trigger an immediate re-crawl from any CMS or CI pipeline after a deploy, instead of waiting
                for the next scheduled crawl. Rotating the secret invalidates whatever was configured before.
              </p>
              <div className={styles.actions}>
                <button className={styles.button} onClick={handleRotateWebhookSecret}>
                  {deployWebhookSecret ? "Rotate secret" : "Generate webhook secret"}
                </button>
              </div>
              {deployWebhookSecret && (
                <div className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <span className={styles.rowMeta}>
                    POST to this URL with header <code>X-RankPilot-Webhook-Secret</code>. Shown once — copy it
                    now:
                  </span>
                  <code style={{ wordBreak: "break-all" }}>
                    {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1"}/websites/{websiteId}/webhooks/deploy
                  </code>
                  <code style={{ wordBreak: "break-all" }}>{deployWebhookSecret}</code>
                </div>
              )}
            </div>
          </>
        )}

        {activeTab === "ai-agents" && (
          <>
            <div className={styles.card}>
              <div className={styles.row} style={{ border: "none", padding: 0 }}>
                <h2>SEO Strategy Assistant</h2>
                <StatusBadge value="drafts_only" tone="info" label="Drafts only — human approval required" />
              </div>
              <p className={styles.rowMeta}>
                Data source: this site&apos;s open opportunities (deterministic, rule-derived). A short
                weekly narrative and focus areas, never a ranking/traffic guarantee.
              </p>
              <button className={`${styles.button} ${styles.buttonPrimary}`} onClick={handleGetWeeklyStrategy}>
                Generate this week&apos;s strategy
              </button>
              {strategySummary && (
                <div className={styles.proposalBox}>
                  <span>{strategySummary.narrative}</span>
                  {strategySummary.focus_areas.map((area, i) => (
                    <span key={i} className={styles.rowMeta}>
                      • {area}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.card}>
              <div className={styles.row} style={{ border: "none", padding: 0 }}>
                <h2>Internal Linking Analyst</h2>
                <StatusBadge value="advisory" tone="info" label="Advisory only" />
              </div>
              <p className={styles.rowMeta}>
                Data source: crawled pages and their internal links. Finds orphan pages (no internal links
                pointing to them) and suggests which existing pages could link to them — there&apos;s no
                connector operation to add a link automatically, so nothing here is ever applied for you.
              </p>
              <button className={styles.button} onClick={handleLoadOrphanPages}>
                Find orphan pages
              </button>
              {orphanPages.length === 0 && (
                <EmptyState
                  title="No orphan pages loaded yet"
                  description={'Click "Find orphan pages" to check for pages nothing else links to.'}
                />
              )}
              {orphanPages.map((page) => (
                <div key={page.id} className={styles.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div className={styles.row} style={{ border: "none", padding: 0 }}>
                    <div className={styles.rowMain}>
                      <span>{page.normalized_url}</span>
                      <span className={styles.rowMeta}>indexability: {page.indexability_state}</span>
                    </div>
                    {!linkSuggestions[page.id] && (
                      <button className={styles.button} onClick={() => handleGetLinkSuggestions(page.id)}>
                        Suggest internal links
                      </button>
                    )}
                  </div>
                  {linkSuggestions[page.id] && (
                    <div className={styles.proposalBox}>
                      {linkSuggestions[page.id].suggestions.length === 0 && (
                        <span className={styles.rowMeta}>No confident suggestions found.</span>
                      )}
                      {linkSuggestions[page.id].suggestions.map((s, i) => (
                        <div key={i} className={styles.proposalActionLine}>
                          {s.source_url} → &quot;{s.anchor_text}&quot; ({s.rationale})
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {activeTab === "reports" && (
          <div className={styles.card}>
            <h2>Weekly reports</h2>
            {reports.length === 0 && (
              <EmptyState title="No reports generated yet" description="Weekly reports are generated automatically once this site has crawl and task history." />
            )}
            {reports.map((report) => {
              const content = report.content_json as {
                crawls?: { count: number; pages_fetched_total: number };
                findings?: { opened_this_period: number; open_now: number };
                opportunities?: { open_now: number };
                changes?: { executed: number; passed_validation: number; failed_validation: number };
                search_performance?: { clicks: number; impressions: number } | null;
                ga4?: { sessions: number; total_users: number; conversions: number } | null;
                disclaimer?: string;
              };
              const metrics: MetricCardMetric[] = [];
              if (content.crawls) {
                metrics.push({ label: "Crawls run", value: content.crawls.count });
                metrics.push({ label: "Pages fetched", value: content.crawls.pages_fetched_total });
              }
              if (content.findings) {
                metrics.push({ label: "Findings opened", value: content.findings.opened_this_period });
                metrics.push({
                  label: "Findings open now",
                  value: content.findings.open_now,
                  attention: content.findings.open_now > 0,
                });
              }
              if (content.opportunities) {
                metrics.push({ label: "Opportunities open", value: content.opportunities.open_now });
              }
              if (content.changes) {
                metrics.push({ label: "Changes executed", value: content.changes.executed });
                metrics.push({ label: "Validation passed", value: content.changes.passed_validation });
                if (content.changes.failed_validation > 0) {
                  metrics.push({
                    label: "Validation failed",
                    value: content.changes.failed_validation,
                    attention: true,
                  });
                }
              }
              if (content.search_performance) {
                metrics.push({ label: "Search clicks", value: content.search_performance.clicks });
                metrics.push({ label: "Search impressions", value: content.search_performance.impressions });
              }
              if (content.ga4) {
                metrics.push({ label: "GA4 sessions", value: content.ga4.sessions });
                metrics.push({ label: "GA4 users", value: content.ga4.total_users });
                metrics.push({ label: "GA4 conversions", value: content.ga4.conversions });
              }
              return (
                <div key={report.id} className={styles.reportBlock}>
                  <p className={styles.rowMeta}>
                    {report.period_start} → {report.period_end}
                  </p>
                  {metrics.length > 0 && <MetricGrid metrics={metrics} />}
                  {content.disclaimer && <p className={styles.rowMeta}>{content.disclaimer}</p>}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {confirmState && (
        <ConfirmDialog
          message={confirmState.message}
          onConfirm={() => {
            const { onConfirm } = confirmState;
            setConfirmState(null);
            onConfirm();
          }}
          onCancel={() => setConfirmState(null)}
        />
      )}
    </div>
  );
}
