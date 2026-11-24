import type { Metadata } from "next";
import Link from "next/link";
import styles from "@/components/site/site.module.css";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Contact | RankPilot AI",
  description: "Questions about RankPilot AI? Get in touch.",
  alternates: { canonical: "/contact" },
};

export default function Contact() {
  return (
    <article className={`${styles.container} ${styles.narrow} ${styles.prose}`}>
      <h1>Contact us</h1>
      <p>Questions about RankPilot, your account, billing, or your data? Email us and a person will reply.</p>
      <p><a className={`${styles.btn} ${styles.btnPrimary}`} href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#fff" }}>{CONTACT_EMAIL}</a></p>
      <h2>Already a customer?</h2>
      <p>The AI Assistant inside the app can answer how-to questions about your project. <Link href="/login">Log in</Link> to use it.</p>
      <h2>Privacy requests</h2>
      <p>To access, export or delete your data, email the address above from the email you registered with.</p>
    </article>
  );
}
