import styles from "@/components/site/site.module.css";
import { CONTACT_EMAIL } from "@/lib/site";
import { pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({ title: "Terms of service", description: "The terms for using RankPilot AI: your account, changes to your website, no guarantee of results, acceptable use, plans and payment.", path: "/terms" });

export default function Terms() {
  return (
    <article className={`${styles.container} ${styles.narrow} ${styles.prose}`}>
      <h1>Terms of service</h1>
      <p className={styles.updated}>Last updated: 24 November 2026</p>
      <p>These terms govern your use of RankPilot AI. By creating an account or using the service you agree to them. Contact: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>

      <h2>The service</h2>
      <p>RankPilot audits websites, prepares SEO recommendations and, when you approve them, applies changes through platforms you connect and checks the results. It also reports on search performance using data you connect.</p>

      <h2>Your account</h2>
      <p>You are responsible for your account, for keeping your password secure, and for the people you invite to your workspace. You must only add websites you own or are authorised to manage, and you may need to verify ownership.</p>

      <h2>Your website and changes</h2>
      <p>Changes to your website are made only through connections you set up, and (unless you opt in to automatic low-risk fixes) only after you approve them. You are responsible for reviewing what you approve. Keep your own backups; RankPilot records before and after values and provides rollback information where the platform allows, but cannot guarantee that a change will not have side effects on your site.</p>

      <h2>No guarantee of results</h2>
      <p>Search rankings and traffic depend on many factors outside our control, including search engines&apos; own decisions. RankPilot does not guarantee any ranking, traffic or revenue outcome. AI-generated suggestions and estimates may be wrong or incomplete and are provided to assist your own judgement.</p>

      <h2>Acceptable use</h2>
      <p>You agree not to misuse the service: for example, to crawl or modify sites you are not authorised to manage, to attempt to bypass limits or security, to interfere with the service, or to break the law. We may suspend access that puts the service or others at risk.</p>

      <h2>Third-party services</h2>
      <p>RankPilot works with services such as Google, WordPress, Shopify, Webflow, Sanity, GitHub, an AI model provider and a payment provider. Your use of those services is subject to their own terms, and their availability is outside our control.</p>

      <h2>Plans, trials and payment</h2>
      <p>Plans are priced per website and billed monthly or yearly as shown on the pricing page at the time you subscribe. Trials, where offered, are described at sign-up. Payments are processed by our payment provider. Taxes may apply.</p>

      <h2>Your data</h2>
      <p>You keep ownership of your content and data. You give us permission to process it only to provide the service, as described in our <a href="/privacy">privacy policy</a>.</p>

      <h2>Availability and liability</h2>
      <p>We work to keep RankPilot available but provide it “as is”, without warranties of any kind to the extent the law allows. To the extent the law allows, our total liability to you for any claim relating to the service is limited to the amount you paid us in the twelve months before the claim, and we are not liable for indirect or consequential losses such as lost profits or traffic.</p>

      <h2>Ending your use</h2>
      <p>You may stop using RankPilot and ask us to delete your account at any time. We may suspend or end access for breach of these terms.</p>

      <h2>Changes</h2>
      <p>We may update these terms. If a change is significant we will tell account holders. Continuing to use the service after a change means you accept it.</p>
    </article>
  );
}
