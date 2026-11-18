"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError, MeResponse, ShopifyItem, ShopifyProposal, ShopifySummary,
  applyShopify, decideShopify, getMe, getShopifyCatalog, getShopifySummary, listShopifyProposals, proposeShopify, rollbackShopify, syncShopify,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import styles from "./shopify.module.css";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const FIELD: Record<string, string> = { seo_title: "Search title", meta_description: "Meta description" };

export default function ShopifySeoPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const websiteId = params.id;
  const [token] = useState(() => getToken());
  const [me, setMe] = useState<MeResponse | null>(null);
  const orgId = me?.organizations[0]?.id;
  const [summary, setSummary] = useState<ShopifySummary | null>(null);
  const [products, setProducts] = useState<ShopifyItem[]>([]);
  const [proposals, setProposals] = useState<ShopifyProposal[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) { router.push("/login"); return; }
    getMe(token).then(setMe).catch((e) => { if (e instanceof ApiError && e.status === 401) router.push("/login"); else setError(msg(e)); });
  }, [token, router]);

  const load = useCallback(() => {
    if (!token || !orgId) return;
    Promise.all([getShopifySummary(token, orgId, websiteId), getShopifyCatalog(token, orgId, websiteId, "products"), listShopifyProposals(token, orgId, websiteId)])
      .then(([s, c, p]) => { setSummary(s); setProducts(c.items); setProposals(p.items); setLoaded(true); })
      .catch((e) => setError(msg(e)));
  }, [token, orgId, websiteId]);
  useEffect(load, [load]);

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key); setError(null);
    try { await fn(); load(); } catch (e) { setError(msg(e)); } finally { setBusy(null); }
  }
  const t = token!, o = orgId!;

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <Link href={`/dashboard/websites/${websiteId}`} className={styles.back}>← Back to project</Link>
          <h1>Shopify SEO</h1>
          <p className={styles.sub}>Reads your products and collections, finds SEO problems, and drafts fixes. Nothing changes in your store until you approve it.</p>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}

        <section className={styles.card} aria-label="Catalog">
          <h2>Catalog</h2>
          {loaded && summary && summary.last_synced_at === null && <p className={styles.empty} data-testid="not-synced">The catalog has not been read yet. Connect your Shopify store, then read it.</p>}
          {summary?.last_synced_at && (
            <div className={styles.stats} data-testid="summary">
              <div className={styles.stat}><div className={styles.statLabel}>Products</div><div className={styles.statValue}>{summary.products}</div></div>
              <div className={styles.stat}><div className={styles.statLabel}>Collections</div><div className={styles.statValue}>{summary.collections}</div></div>
              <div className={styles.stat}><div className={styles.statLabel}>Products with issues</div><div className={styles.statValue}>{summary.products_with_issues}</div></div>
            </div>
          )}
          <div className={styles.row}>
            <button className={styles.btn} disabled={busy !== null || !orgId} onClick={() => run("sync", () => syncShopify(t, o, websiteId))}>{busy === "sync" ? "Reading…" : "Read my store (no changes)"}</button>
            {summary?.last_synced_at && <span className={styles.small}>Last read {new Date(summary.last_synced_at).toLocaleString()}</span>}
          </div>
          {products.map((p) => (
            <article key={p.id} className={styles.rec} data-testid="product">
              <h3>{p.title}</h3>
              <ul className={styles.list}>
                {p.issues.length === 0 && <li className={styles.small}>No issues found.</li>}
                {p.issues.map((i) => <li key={i.code}><span><span className={styles.badge}>{i.severity}</span> {i.message}</span></li>)}
              </ul>
              <div className={styles.row}><button className={styles.btn} disabled={busy !== null} onClick={() => run(`p${p.external_id}`, () => proposeShopify(t, o, websiteId, p.external_id))}>Draft SEO text with AI</button></div>
            </article>
          ))}
        </section>

        <section className={styles.card} aria-label="Proposed changes">
          <h2>Proposed changes</h2>
          {proposals.length === 0 && <p className={styles.empty}>No drafts yet.</p>}
          {proposals.map((r) => (
            <article key={r.id} className={styles.rec} data-testid="proposal">
              <h3>{r.title} — {FIELD[r.field] ?? r.field} <span className={styles.badge}>{r.status.replace("_", " ")}</span></h3>
              <span className={styles.small}>Now: {r.before_value || "(empty)"}</span>
              <span><strong>Proposed:</strong> {r.proposed_value}</span>
              <span className={styles.small}>{r.label}</span>
              {r.failure && <span className={styles.warn}>{r.failure}</span>}
              {r.status === "applied" && <span className={styles.small}>{r.verified ? "Confirmed by reading the live value back." : "Not confirmed on read-back."}</span>}
              <div className={styles.row}>
                {r.status === "draft" && <><button className={styles.btn} disabled={busy !== null} onClick={() => run(r.id, () => decideShopify(t, o, websiteId, r.id, "approve"))}>Approve</button>
                  <button className={styles.btn} disabled={busy !== null} onClick={() => run(r.id, () => decideShopify(t, o, websiteId, r.id, "reject"))}>Reject</button></>}
                {(r.status === "approved") && <button className={styles.btn} disabled={busy !== null} onClick={() => run(r.id, () => applyShopify(t, o, websiteId, r.id))}>Apply to store</button>}
                {r.status === "applied" && <button className={styles.btn} disabled={busy !== null} onClick={() => run(r.id, () => rollbackShopify(t, o, websiteId, r.id))}>Undo</button>}
              </div>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
