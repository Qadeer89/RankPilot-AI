import styles from "@/components/site/site.module.css";
import { CONTACT_EMAIL } from "@/lib/site";
import { pageMeta } from "@/lib/marketing";

export const metadata = pageMeta({ title: "Privacy policy", description: "What data RankPilot AI collects, how it is used, how Google data is handled, and your choices.", path: "/privacy" });

export default function Privacy() {
  return (
    <article className={`${styles.container} ${styles.narrow} ${styles.prose}`}>
      <h1>Privacy policy</h1>
      <p className={styles.updated}>Last updated: 24 November 2026</p>
      <p>RankPilot AI (“RankPilot”, “we”) helps website owners audit their sites and improve their search presence. This page explains what we collect, why, and the choices you have. Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>

      <h2>What we collect</h2>
      <ul>
        <li><strong>Account details:</strong> your name, email address and a securely hashed password, and the workspace (organization) you belong to.</li>
        <li><strong>Website data:</strong> the addresses of the websites you add, and what our crawler reads from their public pages: titles, descriptions, headings, links, images, structured data and page text characteristics. We respect robots.txt and crawl limits.</li>
        <li><strong>Google Search Console data (only if you connect it):</strong> search queries, clicks, impressions, average position, and indexing status for the properties you choose.</li>
        <li><strong>Google Analytics 4 data (only if you connect it):</strong> aggregate organic landing-page measurements for the property you choose.</li>
        <li><strong>Platform connection details (only if you connect a platform):</strong> for example a WordPress application password or a Shopify, Webflow, Sanity or GitHub token, used to apply changes you approve.</li>
        <li><strong>Billing details:</strong> payments are handled by our payment provider. We receive confirmation of your subscription and payment status, not your card number.</li>
        <li><strong>Usage records:</strong> which changes were proposed, approved and applied, and basic logs needed to run and secure the service.</li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To run the audit, prepare recommendations and, when you approve them, apply changes and check they are live.</li>
        <li>To show your progress and history over time.</li>
        <li>To operate, secure and improve the service, and to contact you about your account.</li>
      </ul>

      <h2>Google user data</h2>
      <p>If you connect Google Search Console, we ask only for <strong>read-only</strong> access. We use that data solely to show you your own search performance and indexing status and to prepare recommendations for your own website inside RankPilot.</p>
      <p>RankPilot&apos;s use and transfer of information received from Google APIs adheres to the <a href="https://developers.google.com/terms/api-services-user-data-policy" rel="noopener noreferrer">Google API Services User Data Policy</a>, including the Limited Use requirements. We do not sell Google user data, do not use it for advertising, and do not use it to train general-purpose AI models. You can disconnect Google at any time from the Integrations page, and also revoke access from your Google Account settings.</p>

      <h2>AI processing</h2>
      <p>To draft titles, descriptions and similar suggestions we send limited page content and context (for example a page&apos;s existing title and headings) to an AI model provider. We do not send your password, payment details or connection credentials. Suggestions are labelled as AI-generated and need your approval before they are applied.</p>

      <h2>How we protect it</h2>
      <p>Connection tokens and credentials are stored encrypted. Access to a workspace is limited to its members according to their role. Connections to RankPilot use HTTPS. No system is perfectly secure, so please use a strong, unique password.</p>

      <h2>Sharing</h2>
      <p>We share data only with service providers that help us run RankPilot (hosting, our AI model provider, our payment provider and email delivery), and only as needed for them to do so. We do not sell personal data.</p>

      <h2>Retention and deletion</h2>
      <p>We keep your data while your account is active so your history and baseline remain available. You can disconnect integrations at any time, and you can ask us to delete your account and associated data by emailing <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Some billing and security records may be kept for as long as the law requires.</p>

      <h2>Your choices</h2>
      <p>You can access, correct or export your information, disconnect Google or any platform, and request deletion. Contact us and we will respond promptly.</p>

      <h2>Changes</h2>
      <p>If we change this policy we will update the date above and, for significant changes, tell account holders.</p>
    </article>
  );
}
