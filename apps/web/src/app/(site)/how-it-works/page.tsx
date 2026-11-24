import Link from "next/link";
import Screenshot from "@/components/site/Screenshot";
import styles from "@/components/site/site.module.css";
import { JOURNEY, STEPS, pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({
  title: "How RankPilot AI works",
  description: "Add your website, analyze your SEO, discover opportunities, review recommendations, implement approved improvements and track your progress.",
  path: "/how-it-works",
});

const SHOTS = ["overview", "findings", "growth-plan", "keywords", "findings", "history"] as const;
const ALTS = ["Project overview with an SEO health score", "Findings grouped by rule with explanations", "Growth plan with next actions", "Keyword opportunities labelled by data source", "Findings and recommendations with evidence", "Progress compared with the saved starting point"];

export default function HowItWorks() {
  return (
    <>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>From a website address to verified improvements.</h1>
          <p>RankPilot follows one loop and repeats it as your site changes.</p>
          <ol className={`${styles.journey} ${styles.journeyLight}`} aria-label="The RankPilot workflow">{JOURNEY.map((j) => <li key={j}>{j}</li>)}</ol>
        </div>
      </section>
      <section className={styles.container} style={{ paddingBottom: 24 }}>
        {STEPS.map((s, i) => (
          <article key={s.t} className={styles.featureRow}>
            <div className={styles.featureText}>
              <span className={styles.flowNum} aria-hidden="true">{s.icon}</span>
              <h2>{s.t}</h2>
              <p>{s.d}</p>
            </div>
            <Screenshot name={SHOTS[i]} alt={ALTS[i]} />
          </article>
        ))}
        <p className={styles.note} style={{ margin: "8px 0 40px" }}>Which steps are available depends on the integrations and permissions you connect. Without a connected platform, RankPilot gives you the exact change to make instead of applying it. Without Search Console, search performance is simply shown as not available.</p>
      </section>
      <section className={styles.section} style={{ paddingTop: 0 }}>
        <div className={styles.container}>
          <div className={styles.cta}>
            <h2>Start with your first audit</h2>
            <p>Add your website and see what RankPilot finds.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnAccent} ${styles.btnLarge}`}>Start free</Link>
          </div>
        </div>
      </section>
    </>
  );
}
