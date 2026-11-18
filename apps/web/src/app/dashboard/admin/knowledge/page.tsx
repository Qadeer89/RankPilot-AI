"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AdminChatFeedback,
  AdminKnowledgeDocument,
  ApiError,
  KnowledgeIngestionJob,
  MeResponse,
  createAdminKnowledgeDocument,
  getMe,
  listAdminChatFeedback,
  listAdminKnowledgeDocuments,
  listKnowledgeIngestionJobs,
  runKnowledgeReindex,
  updateAdminKnowledgeDocument,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "./knowledge.module.css";

type Tab = "documents" | "ingestion" | "feedback";
type Filter = "all" | "customer" | "internal";

const TEMPLATE = `Question: (what a customer would ask, in their own words)

Short answer: (1-2 sentences)

Steps:
1. (what to click, in order)
2. 
3. 

Notes: (limits, what RankPilot cannot do, when to contact support)`;

const isInternal = (d: { source_type: string }) => d.source_type === "seed_docs";

const CATEGORY_OPTIONS = [
  "general",
  "onboarding",
  "ai_automation",
  "seo_automation",
  "connectors",
  "security",
  "architecture",
  "qa",
  "deployment",
];

function DocumentForm({
  initial,
  onSubmit,
  onCancel,
}: {
  initial?: AdminKnowledgeDocument;
  onSubmit: (payload: { title: string; category: string; content: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [category, setCategory] = useState(initial?.category ?? CATEGORY_OPTIONS[0]);
  const [content, setContent] = useState(initial?.content ?? "");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSubmit({ title, category, content });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.formRow}>
        <input
          className={styles.input}
          placeholder="Title"
          aria-label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <select className={styles.select} aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORY_OPTIONS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      {!initial && (
        <button type="button" className={styles.secondaryButton} style={{ alignSelf: "flex-start" }} onClick={() => setContent((c) => c || TEMPLATE)}>
          Use help-article template
        </button>
      )}
      <textarea
        className={styles.textarea}
        placeholder="Article content (plain text or markdown)"
        aria-label="Content"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        required
      />
      <div className={styles.formRow}>
        <button type="submit" className={styles.primaryButton} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function AdminKnowledgePage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<Tab>("documents");
  const [error, setError] = useState<string | null>(null);

  const [documents, setDocuments] = useState<AdminKnowledgeDocument[]>([]);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<Filter>("customer");
  const [editingId, setEditingId] = useState<string | null>(null);

  const [jobs, setJobs] = useState<KnowledgeIngestionJob[]>([]);
  const [reindexing, setReindexing] = useState(false);

  const [feedback, setFeedback] = useState<AdminChatFeedback[]>([]);
  const [unansweredOnly, setUnansweredOnly] = useState(true);

  const token = getToken();

  useEffect(() => {
    const activeToken = getToken();
    if (!activeToken) {
      router.push("/login");
      return;
    }
    getMe(activeToken)
      .then(setMe)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load."))
      .finally(() => setLoaded(true));
  }, [router]);

  useEffect(() => {
    if (!token || !me?.user.is_platform_admin) return;
    if (tab === "documents") {
      listAdminKnowledgeDocuments(token).then(setDocuments).catch(() => setError("Failed to load documents."));
    } else if (tab === "ingestion") {
      listKnowledgeIngestionJobs(token).then(setJobs).catch(() => setError("Failed to load ingestion jobs."));
    } else if (tab === "feedback") {
      listAdminChatFeedback(token, unansweredOnly).then(setFeedback).catch(() => setError("Failed to load feedback."));
    }
  }, [tab, token, me, unansweredOnly]);

  async function handleCreate(payload: { title: string; category: string; content: string }) {
    if (!token) return;
    setError(null);
    try {
      const created = await createAdminKnowledgeDocument(token, payload);
      setDocuments((prev) => [created, ...prev]);
      setCreating(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save the document.");
    }
  }

  async function handleUpdate(id: string, payload: { title?: string; category?: string; content?: string }) {
    if (!token) return;
    setError(null);
    try {
      const updated = await updateAdminKnowledgeDocument(token, id, payload);
      setDocuments((prev) => prev.map((d) => (d.id === id ? updated : d)));
      setEditingId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save the document.");
    }
  }

  async function handleToggleActive(document: AdminKnowledgeDocument) {
    if (!token) return;
    setError(null);
    try {
      const updated = await updateAdminKnowledgeDocument(token, document.id, { is_active: !document.is_active });
      setDocuments((prev) => prev.map((d) => (d.id === document.id ? updated : d)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update the document.");
    }
  }

  async function handleReindex() {
    if (!token) return;
    setReindexing(true);
    try {
      const job = await runKnowledgeReindex(token);
      setJobs((prev) => [job, ...prev]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Re-index failed.");
    } finally {
      setReindexing(false);
    }
  }

  if (!loaded) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>Loading...</div>
      </div>
    );
  }

  if (!me?.user.is_platform_admin) {
    return (
      <div className={styles.page}>
        <div className={styles.container}>
          <p className={styles.error} role="alert">
            You don&apos;t have access to this page.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <div>
            <h1>Knowledge Base Admin</h1>
            <p>Manage what the AI Assistant knows, re-index content, and review feedback.</p>
          </div>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}

        <div className={styles.tabs}>
          <button type="button" className={`${styles.tab} ${tab === "documents" ? styles.tabActive : ""}`} onClick={() => setTab("documents")}>
            Documents
          </button>
          <button type="button" className={`${styles.tab} ${tab === "ingestion" ? styles.tabActive : ""}`} onClick={() => setTab("ingestion")}>
            Ingestion
          </button>
          <button type="button" className={`${styles.tab} ${tab === "feedback" ? styles.tabActive : ""}`} onClick={() => setTab("feedback")}>
            Feedback
          </button>
        </div>

        {tab === "documents" && (
          <div className={styles.card}>
            <div className={styles.explain} data-testid="kb-explain">
              <strong>What is this?</strong> The AI Assistant answers customers&apos; questions using these articles. <strong>Customer help articles</strong> are
              written by you in plain language (for example &ldquo;How do I connect Google Search Console?&rdquo;). <strong>Internal technical docs</strong> are
              RankPilot&apos;s own engineering documents; they are loaded automatically, help the assistant describe how the product works, and are not meant to be
              edited here. After adding or changing an article, open the <em>Ingestion</em> tab and press <em>Re-index now</em> so the assistant uses it.
            </div>
            <div className={styles.formRow} role="group" aria-label="Show">
              {([["customer", "Customer help articles"], ["internal", "Internal technical docs"], ["all", "All"]] as [Filter, string][]).map(([key, text]) => (
                <button key={key} type="button" aria-pressed={filter === key} className={`${styles.secondaryButton} ${filter === key ? styles.tabActive : ""}`} onClick={() => setFilter(key)}>
                  {text} ({documents.filter((d) => key === "all" || (key === "internal") === isInternal(d)).length})
                </button>
              ))}
            </div>
            <div className={styles.cardHeader}>
              <h2>Articles</h2>
              <button type="button" className={styles.primaryButton} onClick={() => setCreating((v) => !v)}>
                {creating ? "Close" : "+ New document"}
              </button>
            </div>

            {creating && <DocumentForm onSubmit={handleCreate} onCancel={() => setCreating(false)} />}

            {documents.filter((d) => filter === "all" || (filter === "internal") === isInternal(d)).length === 0 && !creating && (
              <p className={styles.empty}>
                {filter === "customer"
                  ? "No customer help articles yet. Click “+ New document” and use the help-article template to write the first one."
                  : "Nothing here."}
              </p>
            )}

            {documents.filter((d) => filter === "all" || (filter === "internal") === isInternal(d)).map((document) =>
              editingId === document.id ? (
                <DocumentForm
                  key={document.id}
                  initial={document}
                  onSubmit={(payload) => handleUpdate(document.id, payload)}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <div key={document.id} className={styles.docRow}>
                  <div className={styles.docRowHeader}>
                    <span className={styles.docTitle}>{document.title}</span>
                    <span className={document.is_active ? styles.badge : `${styles.badge} ${styles.badgeInactive}`}>
                      {document.is_active ? "active" : "inactive"}
                    </span>
                  </div>
                  <span className={styles.docMeta}>
                    {isInternal(document) ? "Internal technical doc" : "Customer help article"} &middot; {document.category} &middot; v{document.version}
                  </span>
                  <div className={styles.actionRow}>
                    {!isInternal(document) && (
                      <button type="button" className={styles.secondaryButton} onClick={() => setEditingId(document.id)}>
                        Edit
                      </button>
                    )}
                    <button type="button" className={styles.secondaryButton} onClick={() => handleToggleActive(document)}>
                      {document.is_active ? "Disable" : "Enable"}
                    </button>
                  </div>
                </div>
              )
            )}
          </div>
        )}

        {tab === "ingestion" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Re-index</h2>
              <button type="button" className={styles.primaryButton} onClick={handleReindex} disabled={reindexing}>
                {reindexing ? "Re-indexing..." : "Re-index now"}
              </button>
            </div>
            {jobs.length === 0 && <p className={styles.empty}>No ingestion runs yet.</p>}
            {jobs.map((job) => (
              <div key={job.id} className={styles.docRow}>
                <div className={styles.docRowHeader}>
                  <span className={styles.docTitle}>{job.status}</span>
                  <span className={styles.docMeta}>{job.started_at}</span>
                </div>
                <span className={styles.docMeta}>
                  {job.documents_processed} docs processed, {job.chunks_created} chunks created
                </span>
                {job.error && <span className={styles.error}>{job.error}</span>}
              </div>
            ))}
          </div>
        )}

        {tab === "feedback" && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Chatbot feedback</h2>
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={unansweredOnly}
                  onChange={(e) => setUnansweredOnly(e.target.checked)}
                />
                Unanswered questions only
              </label>
            </div>
            {feedback.length === 0 && <p className={styles.empty}>No feedback to show.</p>}
            {feedback.map((item) => (
              <div key={item.id} className={styles.feedbackRow}>
                <span className={styles.feedbackQuestion}>{item.question || "(no question captured)"}</span>
                <span className={styles.feedbackAnswer}>{item.answer}</span>
                <span className={styles.feedbackMeta}>
                  {item.rating === "up" ? "👍" : "👎"} {new Date(item.created_at).toLocaleString()}
                  {item.note ? ` -- "${item.note}"` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
