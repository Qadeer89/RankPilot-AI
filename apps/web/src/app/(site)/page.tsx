import type { Metadata } from "next";
import Link from "next/link";
import styles from "@/components/site/site.module.css";
import { getPublicPricing, money } from "@/lib/publicPricing";
import { FAQ } from "./faq";

export const metadata: Metadata = {
  title: "RankPilot AI: SEO that finds, fixes and proves its own work",
  description: "RankPilot AI audits your website, prepares SEO fixes for your approval, checks they went live, and tracks real progress from your own Google data. No ranking promises.",
  alternates: { canonical: "/" },
};

const STEPS = [
  { n: "Step 1", t: "Add your website", d: "Verify you own it, optionally connect Google Search Console, and tell RankPilot what your business offers." },
  { n: "Step 2", t: "RankPilot audits it", d: "It crawls the site like a search engine would and lists what is holding it back, in plain language, with the evidence." },
  { n: "Step 3", t: "You approve the fixes", d: "Titles, descriptions, links and more are prepared for you. Nothing changes on your site until you approve it." },
  { n: "Step 4", t: "It checks and reports", d: "After a change RankPilot reads the live page to confirm it worked, then tracks progress against where you started." },
];

const FEATURES = [
  { i: "🔍", t: "Clear site audit", d: "Every problem comes with what it means, why it matters and how to fix it. Repeated issues from one template show up as one problem, not 143." },
  { i: "✅", t: "Fixes you approve", d: "AI prepares the change, you review and approve it. Risky edits always wait for you; routine ones can run automatically only if you opt in." },
  { i: "🛰️", t: "Live verification", d: "RankPilot re-reads the published page and tells you whether the change is really live, still pending, or showing the old value." },
  { i: "📈", t: "Honest progress tracking", d: "Your starting point is saved. Search Console results are compared fairly over time, and small numbers are never dressed up as wins." },
  { i: "🧭", t: "Keyword and content ideas", d: "Ideas from your own pages and Search Console queries, clearly labelled: verified data, AI estimate, or not available." },
  { i: "🔗", t: "Works with your platform", d: "WordPress, Shopify, Webflow, Sanity and GitHub-based sites, or audit-only mode for any site." },
];

export default async function Home() {
  const pricing = await getPublicPricing();
  const monthly = pricing?.plans.find((p) => p.interval === "month");
  const trial = monthly?.trial_days;
  return (
    <>
      <section className={styles.hero}>
        <div className={`${styles.container} ${styles.heroGrid}`}>
          <div>
            <span className={styles.eyebrow}>For businesses and agencies that want real SEO progress</span>
            <h1>SEO that finds, fixes and proves its own work.</h1>
            <p className={styles.lead}>
              RankPilot AI audits your website, prepares the fixes for your approval, checks they actually went live, and shows progress from your own Google data. No guesses, no ranking promises.
            </p>
            <div className={styles.heroActions}>
              <Link href="/register" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLarge}`}>{trial ? `Start your ${trial}-day trial` : "Create your account"}</Link>
              <Link href="#how-it-works" className={`${styles.btn} ${styles.btnGhost} ${styles.btnLarge}`}>See how it works</Link>
            </div>
            <p className={styles.heroNote}>Already have an account? <Link href="/login" style={{ color: "inherit", textDecoration: "underline" }}>Log in</Link></p>
          </div>
          <div className={styles.demo} aria-label="Example workflow">
            <span className={styles.demoTag}>Example workflow (illustration)</span>
            <div className={`${styles.demoStep} ${styles.demoDone}`}><span className={styles.demoDot}>1</span><div><strong>Found: page title too long</strong><span>Google would cut it off in search results.</span></div></div>
            <div className={`${styles.demoStep} ${styles.demoDone}`}><span className={styles.demoDot}>2</span><div><strong>Fix prepared</strong><span>A shorter title that keeps the topic first.</span></div></div>
            <div className={`${styles.demoStep} ${styles.demoDone}`}><span className={styles.demoDot}>3</span><div><strong>You approved it</strong><span>Nothing is changed without this step.</span></div></div>
            <div className={`${styles.demoStep} ${styles.demoDone}`}><span className={styles.demoDot}>✓</span><div><strong>Confirmed on the live page</strong><span>RankPilot re-read the page and saw the new title.</span></div></div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className={styles.section}>
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2>How it works</h2>
            <p>Four steps from a website address to verified improvements.</p>
          </div>
          <div className={styles.grid4}>
            {STEPS.map((s) => (
              <div key={s.t} className={styles.card}><span className={styles.step}>{s.n}</span><h3>{s.t}</h3><p>{s.d}</p></div>
            ))}
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionAlt}`}>
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2>Everything in one place</h2>
            <p>Audit, fixes, verification and reporting, without stitching together five tools.</p>
          </div>
          <div className={styles.grid3}>
            {FEATURES.map((f) => (
              <div key={f.t} className={styles.card}><span className={styles.iconBox} aria-hidden="true">{f.i}</span><h3>{f.t}</h3><p>{f.d}</p></div>
            ))}
          </div>
          <p style={{ marginTop: 24 }}><Link href="/features" className={`${styles.btn} ${styles.btnGhost}`}>See all features</Link></p>
        </div>
      </section>

      <section className={styles.section}>
        <div className={`${styles.container} ${styles.grid2}`} style={{ alignItems: "start" }}>
          <div className={styles.sectionHead} style={{ marginBottom: 0 }}>
            <h2>Honest by design</h2>
            <p>SEO tools are full of invented numbers. RankPilot is built the other way round.</p>
          </div>
          <ul className={styles.promise}>
            <li>We never promise rankings or traffic. Nobody can, and a tool that does is guessing.</li>
            <li>Every number says where it came from: your crawl, your Google data, a calculation, or an AI estimate.</li>
            <li>If data is missing it says “not available”, never a made-up zero or a made-up score.</li>
            <li>AI suggestions are labelled as suggestions, and you approve before anything is published.</li>
            <li>No paid third-party SEO data is pretended to be ours: no invented search volumes, difficulty scores or backlink totals.</li>
          </ul>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionAlt}`}>
        <div className={styles.container}>
          <div className={styles.sectionHead}>
            <h2>Simple pricing</h2>
            <p>{pricing ? "One plan per website. Pick monthly or save with yearly." : "One plan per website, billed monthly or yearly. See the pricing page for the current prices."}</p>
          </div>
          {pricing && (
            <div className={styles.plans}>
              {pricing.plans.map((p) => (
                <div key={p.interval} className={`${styles.plan} ${p.interval === "year" ? styles.planFeatured : ""}`}>
                  {p.interval === "year" && pricing.annual_saving_cents > 0 && <span className={styles.badge}>Save {money(pricing.annual_saving_cents, p.currency)} a year</span>}
                  <strong>{p.interval === "year" ? "Yearly" : "Monthly"}</strong>
                  <div className={styles.price}>{money(p.price_cents, p.currency)}<small> / {p.interval === "year" ? "year" : "month"} per website</small></div>
                  <Link href="/register" className={`${styles.btn} ${p.interval === "year" ? styles.btnPrimary : styles.btnGhost}`}>{p.trial_days ? `Start ${p.trial_days}-day trial` : "Get started"}</Link>
                </div>
              ))}
            </div>
          )}
          <p style={{ marginTop: 20 }}><Link href="/pricing" className={`${styles.btn} ${styles.btnGhost}`}>What is included</Link></p>
        </div>
      </section>

      <section id="faq" className={styles.section}>
        <div className={styles.container}>
          <div className={styles.sectionHead}><h2>Questions</h2></div>
          <div className={styles.faq}>
            {FAQ.map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}
          </div>
        </div>
      </section>

      <section className={styles.section} style={{ paddingTop: 0 }}>
        <div className={styles.container}>
          <div className={styles.cta}>
            <h2>See what is holding your site back</h2>
            <p>Add your website and get a plain-language audit with the evidence behind every finding.</p>
            <Link href="/register" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLarge}`}>{trial ? `Start your ${trial}-day trial` : "Create your account"}</Link>
          </div>
        </div>
      </section>
    </>
  );
}
