import type { Metadata } from "next";
import Link from "next/link";
import styles from "@/components/site/site.module.css";
import { getPublicPricing, money } from "@/lib/publicPricing";
import { FAQ } from "../faq";

export const metadata: Metadata = {
  title: "Pricing | RankPilot AI",
  description: "One plan per website, billed monthly or yearly, with a free trial. Everything is included.",
  alternates: { canonical: "/pricing" },
};

const INCLUDED = [
  "Full site audit with evidence and explanations",
  "AI-prepared fixes with approval before anything changes",
  "Live verification after every change",
  "Google Search Console progress tracking and history",
  "Keyword, content and technical intelligence",
  "Backlink verification and Domain Quality tracking",
  "Client progress report",
  "Platform connectors: WordPress, Shopify, Webflow, Sanity, GitHub",
];

export default async function Pricing() {
  const pricing = await getPublicPricing();
  return (
    <>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>Simple pricing, per website.</h1>
          <p>One plan with everything included. Choose monthly, or save with yearly. {pricing?.plans[0]?.trial_days ? `Every plan starts with a ${pricing.plans[0].trial_days}-day free trial.` : ""}</p>
        </div>
      </section>
      <section className={styles.container} style={{ paddingBottom: 56 }}>
        {pricing ? (
          <div className={styles.plans}>
            {pricing.plans.map((p) => (
              <div key={p.interval} className={`${styles.plan} ${p.interval === "year" ? styles.planFeatured : ""}`}>
                {p.interval === "year" && pricing.annual_saving_cents > 0 && <span className={styles.badge}>Save {money(pricing.annual_saving_cents, p.currency)} a year</span>}
                <strong>{p.interval === "year" ? "Yearly" : "Monthly"}</strong>
                <div className={styles.price}>{money(p.price_cents, p.currency)}<small> / {p.interval === "year" ? "year" : "month"}</small></div>
                {p.interval === "year" && <span style={{ color: "var(--rp-muted)", fontSize: 14 }}>That is {money(p.monthly_equivalent_cents, p.currency)} a month, per website.</span>}
                <ul className={styles.ticks}>{INCLUDED.slice(0, 4).map((x) => <li key={x}>{x}</li>)}<li>…and everything below</li></ul>
                <Link href="/register" className={`${styles.btn} ${p.interval === "year" ? styles.btnPrimary : styles.btnGhost}`}>{p.trial_days ? `Start ${p.trial_days}-day trial` : "Get started"}</Link>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.card} style={{ maxWidth: 560 }}>
            <h3>Current prices are shown when you sign up</h3>
            <p>We could not load the price list just now. Please try again in a moment, or create an account to see it.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnPrimary}`} style={{ alignSelf: "flex-start" }}>Create your account</Link>
          </div>
        )}
        <h2 style={{ marginTop: 48 }}>Included in every plan</h2>
        <ul className={styles.ticks} style={{ columns: 2, maxWidth: 800 }}>{INCLUDED.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
      <section className={`${styles.section} ${styles.sectionAlt}`}>
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2>Questions</h2></div>
          <div className={styles.faq}>{FAQ.map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}</div>
        </div>
      </section>
    </>
  );
}
