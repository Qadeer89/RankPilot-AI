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
  QaSummary,
  Report,
  SEOFinding,
  SEOTask,
  SearchPerformance,
  StrategySummary,
  Website,
  WebsiteConnection,
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
  getQaSummary,
  getSearchPerformance,
  getSearchProperties,
  getWebsite,
  getWeeklyStrategy,
  listConnections,
  listCrawls,
  listFindings,
  listOpportunities,
  listOrphanPages,
  listPages,
  listReports,
  listTasks,
  pauseWebsite,
  rejectTask,
  cancelTask,
  rollbackChange,
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

const TABS = [
  "overview",
  "crawls",
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
    if (site.search_console_site_url) setSitePropertyInput(site.search_console_site_url);
    if (site.ga4_property_id) setGa4PropertyInput(site.ga4_property_id);
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
    if (site.ga4_property_id) {
      try {
        setGa4Metrics(await getGa4Metrics(token, orgId, websiteId));
      } catch {
        // GA4 may not actually be connected yet; ignore.
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
            <div className={styles.card}>
              <h2>Site health</h2>
              <MetricGrid
                metrics={[
                  { label: "Pages crawled", value: pages.length },
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
            {crawls.map((crawl) => (
              <div key={crawl.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span>{crawl.trigger} crawl</span>
                  <span className={styles.rowMeta}>
                    {crawl.pages_fetched}/{crawl.pages_requested} pages fetched
                    {crawl.error_summary ? ` — ${crawl.error_summary}` : ""}
                  </span>
                </div>
                <StatusBadge value={crawl.status} />
              </div>
            ))}
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
                  if (filtered.length === 0) {
                    return <EmptyState title="No findings match these filters" description="Try a different search term or widen the severity/status filters." />;
                  }
                  return filtered.map((finding) => (
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
                  ));
                })()}
              </>
            )}
          </div>
        )}

        {activeTab === "opportunities" && (
          <div className={styles.card}>
            <h2>Opportunities</h2>
            {opportunities.length > 0 && (
              <label className={styles.rowMeta} style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
                <input
                  type="checkbox"
                  checked={showCompletedOpportunities}
                  onChange={(e) => setShowCompletedOpportunities(e.target.checked)}
                />
                Show completed/resolved ({opportunities.filter((o) => o.status !== "open").length})
              </label>
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
            {tasks.length === 0 && (
              <EmptyState title="No tasks yet" description="A task is created once you accept an AI proposal for an opportunity." />
            )}
            {tasks.map((task) => (
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
