import Link from "next/link";
import Screenshot from "@/components/site/Screenshot";
import styles from "@/components/site/site.module.css";
import { AUDIENCES, DIFFERENTIATORS, FAQ, FEATURES, INTEGRATIONS, JOURNEY, PROBLEMS, STEPS, pageMeta } from "@/lib/marketing";
import { Suspense } from "react";
import { PricingCardsLive, PricingFallback, PricingJsonLd, TrialNote } from "@/components/site/PricingSection";

const HOME_TITLE = "RankPilot AI: AI-powered SEO audit, recommendations and progress tracking";
export const metadata = {
  ...pageMeta({
    title: HOME_TITLE,
    description: "RankPilot AI analyzes your website, finds SEO opportunities, prepares fixes for your approval, checks they went live, and tracks your progress from your own Google data. No ranking guarantees.",
    path: "/",
  }),
  title: { absolute: HOME_TITLE },
};

export default function Home() {
  const shown = FEATURES.slice(0, 6);
  return (
    <>
      <Suspense fallback={null}><PricingJsonLd /></Suspense>

      <section className={styles.hero}>
        <div className={`${styles.container} ${styles.heroGrid}`}>
          <div>
            <span className={styles.eyebrow}>Your AI-powered SEO growth partner</span>
            <h1>Turn SEO insights into measurable growth.</h1>
            <p className={styles.lead}>
              RankPilot AI analyzes your website, identifies opportunities, helps you improve your pages, and tracks your SEO progress, all in one platform.
              Understand your SEO. Discover opportunities. Improve your rankings.
            </p>
            <div className={styles.heroActions}>
              <Link href="/register" className={`${styles.btn} ${styles.btnAccent} ${styles.btnLarge}`}>Start free</Link>
              <Link href="/features" className={`${styles.btn} ${styles.btnGhost} ${styles.btnLarge}`}>Explore features</Link>
            </div>
            <ol className={styles.journey} aria-label="The RankPilot workflow">{JOURNEY.map((j) => <li key={j}>{j}</li>)}</ol>
            <p className={styles.disclaimer}>SEO results depend on search engines, competition, your website and how changes are implemented. RankPilot never guarantees rankings, traffic or sales.</p>
          </div>
          <div className={styles.heroShot}>
            <Screenshot name="overview" priority alt="RankPilot project overview showing an SEO health score of 91, counts of critical issues and warnings, and four score categories" caption="Project overview." />
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="problems">
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2 id="problems">SEO is hard to act on when everything is scattered</h2>
            <p>Most website owners are not short of data. They are short of a clear order of work, and proof that it worked.</p>
          </div>
          <div className={styles.problemGrid}>{PROBLEMS.map((p) => <div key={p.t} className={styles.problem}><h3>{p.t}</h3><p>{p.d}</p></div>)}</div>
          <div className={styles.solution}>
            <p><strong>RankPilot brings the whole workflow together:</strong> analysis, opportunities, recommendations, approved changes, live verification and progress history for your website.</p>
            <Link href="/how-it-works" className={`${styles.btn} ${styles.btnPrimary}`}>See how it works</Link>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionAlt}`} aria-labelledby="features">
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2 id="features">What RankPilot does for your website</h2>
            <p>Every capability below is part of the product today.</p>
          </div>
          <div className={styles.grid3}>{shown.map((f) => <div key={f.slug} className={styles.card}><span className={styles.iconBox} aria-hidden="true">{f.icon}</span><h3>{f.t}</h3><p>{f.d}</p></div>)}</div>
          <p style={{ marginTop: 24 }}><Link href="/features" className={`${styles.btn} ${styles.btnGhost}`}>See all features</Link></p>
        </div>
      </section>

      <section id="how-it-works" className={styles.section} aria-labelledby="how">
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2 id="how">How RankPilot works</h2>
            <p>From a website address to verified improvements. Which steps are available depends on the integrations and permissions you connect.</p>
          </div>
          <ol className={styles.flow} style={{ padding: 0, margin: 0, listStyle: "none" }}>
            {STEPS.map((s) => <li key={s.t} className={styles.flowStep}><span className={styles.flowNum} aria-hidden="true">{s.icon}</span><h3>{s.t}</h3><p>{s.d}</p></li>)}
          </ol>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionAlt}`} aria-labelledby="inside">
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2 id="inside">A look inside</h2>
            <p>These are real RankPilot screens, shown with sample data for a fictional website.</p>
          </div>
          <div className={styles.grid2} style={{ gap: 32 }}>
            <Screenshot name="findings" alt="Findings grouped by rule, with a plain-language explanation and a callout that one shared link causes eight findings" caption="Findings are grouped, explained and tied to evidence." />
            <Screenshot name="growth-plan" alt="Growth Plan showing where the project stands, next actions and the business profile" caption="A growth plan with next actions and the reason for each." />
            <Screenshot name="keywords" alt="Keyword opportunities table with each idea labelled as verified or an AI estimate" caption="Keyword ideas, each labelled by where the data came from." />
            <Screenshot name="history" alt="History and progress comparing the first saved analysis with the latest one" caption="Progress compared with your saved starting point." />
          </div>
          <p style={{ marginTop: 28 }}><Link href="/features" className={`${styles.btn} ${styles.btnGhost}`}>Explore every feature</Link></p>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="who">
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2 id="who">Who RankPilot is for</h2><p>Anyone responsible for how a website performs in search.</p></div>
          <div className={styles.grid4}>{AUDIENCES.map((a) => <div key={a.t} className={styles.card}><h3>{a.t}</h3><p>{a.d}</p></div>)}</div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionAlt}`} aria-labelledby="why">
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2 id="why">Why RankPilot</h2>
            <p>RankPilot is not trying to replace every enterprise SEO suite. It is built to turn your own site data into clear, verified next steps.</p>
          </div>
          <div className={styles.grid4}>{DIFFERENTIATORS.map((d) => <div key={d.t} className={styles.card}><h3>{d.t}</h3><p>{d.d}</p></div>)}</div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="integrations">
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2 id="integrations">Connects to what you already use</h2><p>Only integrations that exist today are listed.</p></div>
          <div className={styles.integrations}>
            {INTEGRATIONS.map((i) => (
              <div key={i.n} className={styles.integration}>
                <strong><span className={styles.mono} aria-hidden="true">{i.n[0]}</span>{i.n}<span className={`${styles.tag} ${i.tag === "Beta" ? styles.tagBeta : ""}`}>{i.tag}</span></strong>
                <p>{i.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="pricing" className={`${styles.section} ${styles.sectionAlt}`} aria-labelledby="pricing-h">
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2 id="pricing-h">Pricing</h2><p>Plans appear here once they are finalized.</p></div>
          <Suspense fallback={<PricingFallback />}><PricingCardsLive compact /></Suspense>
          <p style={{ marginTop: 20 }}><Link href="/pricing" className={`${styles.btn} ${styles.btnGhost}`}>Pricing details</Link></p>
        </div>
      </section>

      <section id="faq" className={styles.section} aria-labelledby="faq-h">
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2 id="faq-h">Frequently asked questions</h2></div>
          <div className={styles.faq}>{FAQ.slice(0, 6).map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}</div>
          <p style={{ marginTop: 20 }}><Link href="/faq" className={`${styles.btn} ${styles.btnGhost}`}>All questions</Link></p>
        </div>
      </section>

      <section className={styles.section} style={{ paddingTop: 0 }}>
        <div className={styles.container}>
          <div className={styles.cta}>
            <h2>Your next SEO improvement starts here.</h2>
            <p>Understand where your website stands and discover what you can improve next.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnAccent} ${styles.btnLarge}`}>Start free with RankPilot</Link>
            <Suspense fallback={null}><TrialNote /></Suspense>
          </div>
        </div>
      </section>
    </>
  );
}
