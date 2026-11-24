import Link from "next/link";
import { getPublicPricing } from "@/lib/publicPricing";
import { SITE_URL } from "@/lib/site";
import JsonLd from "./JsonLd";
import PricingCards from "./PricingCards";
import styles from "./site.module.css";

/** Everything that depends on the live price list. Rendered at request time inside <Suspense> so the rest of each page can be static. */
export async function PricingCardsLive({ compact = false }: { compact?: boolean }) {
  const pricing = await getPublicPricing();
  return <PricingCards pricing={pricing} compact={compact} />;
}

export async function PricingJsonLd({ withUrl = false }: { withUrl?: boolean }) {
  const pricing = await getPublicPricing();
  const monthly = pricing?.plans.find((p) => p.interval === "month");
  return (
    <JsonLd data={{ "@context": "https://schema.org", "@graph": [
      { "@type": "Organization", name: "RankPilot AI", url: SITE_URL },
      { "@type": "WebSite", name: "RankPilot AI", url: SITE_URL },
      { "@type": "SoftwareApplication", name: "RankPilot AI", applicationCategory: "BusinessApplication", operatingSystem: "Web", url: withUrl ? `${SITE_URL}/pricing` : SITE_URL,
        description: "AI-powered SEO audit, recommendations and progress tracking for websites.",
        ...(monthly ? { offers: { "@type": "Offer", price: (monthly.price_cents / 100).toFixed(2), priceCurrency: monthly.currency } } : {}) },
    ] }} />
  );
}

export async function TrialNote() {
  const pricing = await getPublicPricing();
  const trial = pricing?.plans[0]?.trial_days;
  return trial ? <span className={styles.note} style={{ color: "#9aa4c7" }}>{trial}-day free trial for new customers, once per customer. A payment method is collected when you start the trial.</span> : null;
}

export async function PricingTerms() {
  const pricing = await getPublicPricing();
  const trial = pricing?.plans[0]?.trial_days;
  return (
    <ul className={styles.terms}>
      <li>Each website is its own project with its own subscription. You can add as many projects as you need.</li>
      {trial ? <li>A {trial}-day free trial is available once per customer. Projects added after that are billed from the start.</li> : null}
      <li>A payment method is collected when you start a trial. The first charge is made when the trial ends, unless you cancel first.</li>
      <li>You can cancel any time from the Billing page. Cancel during a trial and you are not charged. After a paid period has started, access continues until the end of the period you paid for.</li>
      <li>Prices are shown in the currency above and may be subject to tax at checkout. Payments are processed by our payment provider.</li>
      <li>Creating an account is free and does not need a payment method.</li>
    </ul>
  );
}

export function PricingFallback() {
  return <div className={styles.card} style={{ maxWidth: 560 }} aria-busy="true"><p>Loading current prices…</p><Link href="/register" className={`${styles.btn} ${styles.btnPrimary}`} style={{ alignSelf: "flex-start" }}>Start free</Link></div>;
}
