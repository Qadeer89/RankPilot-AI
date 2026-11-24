import Link from "next/link";
import { Suspense } from "react";
import { PricingCardsLive, PricingFallback, PricingJsonLd, PricingTerms } from "@/components/site/PricingSection";
import styles from "@/components/site/site.module.css";
import { FAQ, pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({
  title: "Pricing: one plan per website, with a free trial",
  description: "One RankPilot AI subscription per website, billed monthly or yearly. Everything is included, with a free trial. Cancel any time.",
  path: "/pricing",
});

const INCLUDED = [
  "Full website SEO audit with evidence and explanations",
  "AI-prepared recommendations; nothing changes without your approval",
  "Live verification after every applied change",
  "Google Search Console and Analytics connections (read-only)",
  "Keyword, competitor, content and technical intelligence",
  "Backlink verification and Domain Quality tracking",
  "History, saved baseline and a client progress report",
  "Every target country you set for the website",
];
const PRICING_FAQ = FAQ.filter((f) => ["What happens after the trial?", "Can I cancel my subscription?", "Can I manage multiple projects?", "Does RankPilot guarantee rankings?"].includes(f.q));

export default function Pricing() {
  return (
    <>
      <Suspense fallback={null}><PricingJsonLd withUrl /></Suspense>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>Simple pricing, per website.</h1>
          <p>One subscription unlocks everything for one website. Choose monthly, or save with yearly. New customers get a free trial, once per customer.</p>
        </div>
      </section>
      <section className={styles.container} style={{ paddingBottom: 48 }}>
        <Suspense fallback={<PricingFallback />}><PricingCardsLive /></Suspense>
        <h2 style={{ marginTop: 48 }}>What one subscription includes</h2>
        <ul className={styles.ticks} style={{ columns: 2, maxWidth: 860 }}>{INCLUDED.map((x) => <li key={x}>{x}</li>)}</ul>
        <h2 style={{ marginTop: 40 }}>Trial, payment and cancellation</h2>
        <Suspense fallback={null}><PricingTerms /></Suspense>
        <div style={{ marginTop: 32 }}><Link href="/register" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLarge}`}>Start free</Link></div>
      </section>
      <section className={`${styles.section} ${styles.sectionAlt}`}>
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2>Billing questions</h2></div>
          <div className={styles.faq}>{PRICING_FAQ.map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}</div>
        </div>
      </section>
    </>
  );
}
