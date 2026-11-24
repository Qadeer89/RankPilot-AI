import Link from "next/link";
import Screenshot from "@/components/site/Screenshot";
import styles from "@/components/site/site.module.css";
import { FEATURES, pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({
  title: "SEO features: audit, recommendations, keywords, competitors and progress tracking",
  description: "Website SEO audit, technical SEO intelligence, AI recommendations, keyword and competitor analysis, content optimization, Google Search Console and Analytics integration, and SEO history.",
  path: "/features",
});

export default function Features() {
  return (
    <>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>Everything you need to understand and improve your SEO.</h1>
          <p>From the first audit to the progress report, every feature says what it knows, how it knows it and what it could not test.</p>
        </div>
      </section>
      <section className={styles.container} style={{ paddingBottom: 32 }}>
        {FEATURES.map((f) => (
          <article key={f.slug} id={f.slug} className={styles.featureRow}>
            <div className={styles.featureText}>
              <span className={styles.iconBox} aria-hidden="true">{f.icon}</span>
              <h2>{f.t}</h2>
              <p>{f.d}</p>
              <ul className={styles.featureBullets}>{f.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
            {f.shot ? <Screenshot name={f.shot} alt={`${f.t} in RankPilot AI`} /> : <div className={styles.noShot} aria-hidden="true">{f.icon}</div>}
          </article>
        ))}
      </section>
      <section className={styles.section} style={{ paddingTop: 0 }}>
        <div className={styles.container}>
          <div className={styles.cta}>
            <h2>Try it on your own website</h2>
            <p>Add a site and see the audit, with the evidence behind every finding.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnAccent} ${styles.btnLarge}`}>Start free</Link>
            <Link href="/pricing" style={{ color: "#c8cee6", fontSize: 14 }}>See pricing</Link>
          </div>
        </div>
      </section>
    </>
  );
}
