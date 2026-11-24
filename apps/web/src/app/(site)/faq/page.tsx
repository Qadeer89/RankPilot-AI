import Link from "next/link";
import JsonLd from "@/components/site/JsonLd";
import styles from "@/components/site/site.module.css";
import { FAQ, pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({
  title: "Frequently asked questions",
  description: "Answers about how RankPilot AI analyzes websites, connects to Google Search Console and Analytics, generates recommendations, tracks progress, and how the trial and billing work.",
  path: "/faq",
});

export default function FaqPage() {
  // FAQ rich results are limited by Google to certain sites, so no FAQPage markup is added; the content is plain, crawlable HTML.
  return (
    <>
      <JsonLd data={{ "@context": "https://schema.org", "@type": "BreadcrumbList", itemListElement: [{ "@type": "ListItem", position: 1, name: "Home", item: "/" }, { "@type": "ListItem", position: 2, name: "FAQ", item: "/faq" }] }} />
      <section className={styles.pageHero}><div className={styles.container}><h1>Frequently asked questions</h1><p>Straight answers about the product, your data and billing.</p></div></section>
      <section className={styles.container} style={{ paddingBottom: 56 }}>
        <div className={styles.faq}>{FAQ.map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}</div>
        <p style={{ marginTop: 28 }}>Something else? <Link href="/contact" style={{ color: "var(--rp-primary)" }}>Contact us</Link>.</p>
      </section>
    </>
  );
}
