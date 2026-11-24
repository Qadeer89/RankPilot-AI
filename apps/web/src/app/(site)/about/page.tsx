import Link from "next/link";
import styles from "@/components/site/site.module.css";
import { pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({
  title: "About RankPilot AI",
  description: "Why RankPilot AI exists, what it believes about SEO, and how it handles data honestly.",
  path: "/about",
});

const PRINCIPLES = [
  { t: "Evidence over guesses", d: "Every finding shows what the crawler saw. Every number says where it came from." },
  { t: "No made-up numbers", d: "If data is missing, RankPilot says “not available”. It does not invent search volume, difficulty, rankings or backlinks." },
  { t: "You stay in control", d: "AI drafts and explains; you approve. Changes are checked on the live page and can be traced back." },
  { t: "Honest about results", d: "SEO takes time and depends on factors nobody controls. RankPilot never guarantees rankings or traffic." },
];

export default function About() {
  return (
    <>
      <section className={styles.pageHero}>
        <div className={styles.container}>
          <h1>SEO tools should show their working.</h1>
          <p>RankPilot AI exists to give website owners a clear, evidence-based way to understand their SEO, decide what to do next, and see whether it worked.</p>
        </div>
      </section>
      <section className={styles.section} style={{ paddingTop: 24 }}>
        <div className={styles.container}>
          <div className={styles.grid2}>{PRINCIPLES.map((p) => <div key={p.t} className={styles.card}><h3>{p.t}</h3><p>{p.d}</p></div>)}</div>
          <div className={`${styles.prose} ${styles.narrow}`} style={{ padding: "40px 0 0" }}>
            <h2>What RankPilot is</h2>
            <p>RankPilot AI is a web application that audits your website, combines the results with your own Google Search Console and Analytics data, prepares recommended improvements for your approval, verifies changes on the live page, and keeps a permanent history of your progress. It is built for businesses, agencies and SEO professionals who want a clear order of work, not another pile of reports.</p>
            <h2>Who is behind it</h2>
            <p>RankPilot AI is a BugSnap AI product. Questions about the product, your data or your account can go to us via the <Link href="/contact">contact page</Link>.</p>
          </div>
        </div>
      </section>
    </>
  );
}
