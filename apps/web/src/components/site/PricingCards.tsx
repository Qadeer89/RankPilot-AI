import Link from "next/link";
import type { PublicPricing } from "@/lib/publicPricing";
import { money } from "@/lib/publicPricing";
import styles from "./site.module.css";

const HIGHLIGHTS = ["Full audit, recommendations and live verification", "Search Console and Analytics connections", "Every target country for the website", "History, baseline and progress report"];

export default function PricingCards({ pricing, compact = false }: { pricing: PublicPricing | null; compact?: boolean }) {
  if (!pricing || !pricing.pricing_finalized || pricing.plans.length === 0) {
    return (
      <div className={styles.card} style={{ maxWidth: 560 }} data-testid="pricing-finalizing">
        <h3>Pricing is being finalized.</h3>
        <p>Create an account to explore RankPilot.</p>
        <Link href="/register" className={`${styles.btn} ${styles.btnPrimary}`} style={{ alignSelf: "flex-start" }}>Create an account</Link>
      </div>
    );
  }
  return (
    <div className={styles.plans}>
      {pricing.plans.map((p) => (
        <div key={p.code} className={`${styles.plan} ${p.interval === "year" ? styles.planFeatured : ""}`}>
          {p.interval === "year" && pricing.annual_saving_cents > 0 && <span className={styles.badge}>Save {money(pricing.annual_saving_cents, p.currency)} a year</span>}
          <strong>{p.name}</strong>
          {p.description && <span className={styles.note}>{p.description}</span>}
          <div className={styles.price}>{money(p.price_cents, p.currency)}<small> / {p.interval === "year" ? "year" : "month"} per website</small></div>
          {p.interval === "year" && <span className={styles.note}>That is {money(p.monthly_equivalent_cents, p.currency)} a month.</span>}
          {!compact && <ul className={styles.ticks}>{HIGHLIGHTS.map((x) => <li key={x}>{x}</li>)}</ul>}
          <Link href="/register" className={`${styles.btn} ${p.interval === "year" ? styles.btnPrimary : styles.btnGhost}`}>{p.trial_days ? `Start ${p.trial_days}-day free trial` : "Get started"}</Link>
        </div>
      ))}
    </div>
  );
}
