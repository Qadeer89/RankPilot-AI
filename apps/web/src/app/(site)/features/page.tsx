import type { Metadata } from "next";
import Link from "next/link";
import styles from "@/components/site/site.module.css";

export const metadata: Metadata = {
  title: "Features | RankPilot AI",
  description: "Site audit, approved fixes, live verification, Search Console progress tracking, keyword and content ideas, and platform connectors, all labelled with where the data came from.",
  alternates: { canonical: "/features" },
};

const FEATURES = [
  { t: "A site audit you can read", p: ["RankPilot crawls your pages like a search engine, respecting robots.txt and crawl limits, and checks titles, descriptions, headings, links, images, structured data, mobile and speed.", "Each finding explains what it means, why it matters and how to fix it, and shows the evidence from the page. Problems that come from one shared template are grouped so one fix clears many pages."], b: ["Plain-language explanations", "Evidence for every finding", "Shared-template problems grouped"] },
  { t: "Fixes prepared, approved by you", p: ["AI drafts the change, such as a shorter title or a missing description, and checks it against the facts on your page before showing it to you.", "You approve, reject or edit. Approve many at once when you are happy. Nothing is written to your site without this step unless you have switched on automatic low-risk fixes."], b: ["Review before anything changes", "Bulk approve and apply", "Kill switch to stop all writing"] },
  { t: "Proof that it went live", p: ["After a change RankPilot reads the published page and tells you whether the new value is live, still being re-checked, or the old one is still showing. Caching delays are handled instead of reported as failures."], b: ["Live check after every change", "Before and after saved", "Rollback information kept"] },
  { t: "Progress you can show a client", p: ["Your starting point is saved the first time a site is analysed and is never overwritten. Later results are compared with it fairly: like with like, with small numbers flagged instead of celebrated.", "A client-ready progress report summarises what was found, what was done and what is still open."], b: ["Permanent baseline", "Search Console comparisons with context", "Printable progress report"] },
  { t: "Keyword and content intelligence", p: ["Ideas come from your own pages and Search Console queries and are grouped into topics and mapped to pages, with possible overlaps between your own pages flagged for review.", "Every idea is labelled: verified from your data, an AI estimate, or not available. Opportunity scores rank queries you already appear for."], b: ["Topic clusters and page mapping", "Queries ranked by opportunity", "Clear data labels"] },
  { t: "Free-first SEO signals", p: ["Content depth, heading structure, trust pages, technical checks such as redirects, social tags and structured data, and a RankPilot Domain Quality score built only from data RankPilot can actually see.", "Backlinks you already know about can be verified live: link present, anchor text, followed or not. RankPilot does not pretend to know every link to your site."], b: ["Documented scoring formulas", "Backlink verification", "No invented authority scores"] },
  { t: "Works with your platform", p: ["Apply approved fixes through WordPress, Shopify, Webflow, Sanity or a GitHub repository, or use audit-only mode on any site. Connection secrets are stored encrypted."], b: ["WordPress, Shopify, Webflow, Sanity, GitHub", "Audit-only mode for anything else", "Encrypted credentials"] },
];

export default function Features() {
  return (
    <>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>Everything you need to improve your SEO, and prove it.</h1>
          <p>From the first audit to the progress report, each step says what it knows, how it knows it and what it does not know.</p>
        </div>
      </section>
      <section className={styles.container} style={{ paddingBottom: 48 }}>
        {FEATURES.map((f) => (
          <div key={f.t} className={styles.feature}>
            <div><h2>{f.t}</h2>{f.p.map((x) => <p key={x}>{x}</p>)}</div>
            <ul className={styles.ticks} style={{ background: "var(--rp-surface)", border: "1px solid var(--rp-border)", borderRadius: 14, padding: 22 }}>
              {f.b.map((x) => <li key={x}>{x}</li>)}
            </ul>
          </div>
        ))}
      </section>
      <section className={styles.section} style={{ paddingTop: 0 }}>
        <div className={styles.container}>
          <div className={styles.cta}>
            <h2>Try it on your own website</h2>
            <p>Add a site and see the audit in minutes.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLarge}`}>Create your account</Link>
          </div>
        </div>
      </section>
    </>
  );
}
