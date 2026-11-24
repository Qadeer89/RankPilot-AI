import Link from "next/link";
import { CONTACT_EMAIL } from "@/lib/site";
import styles from "./site.module.css";

export default function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.container}>
        <div className={styles.footerGrid}>
          <div>
            <Link href="/" className={styles.brand}>RankPilot <span>AI</span></Link>
            <p>Finds what holds your website back in search, prepares the fixes for your approval, and checks they went live.</p>
          </div>
          <div>
            <h4>Product</h4>
            <Link href="/features">Features</Link>
            <Link href="/pricing">Pricing</Link>
            <Link href="/#how-it-works">How it works</Link>
            <Link href="/#faq">FAQ</Link>
          </div>
          <div>
            <h4>Account</h4>
            <Link href="/login">Log in</Link>
            <Link href="/register">Create an account</Link>
          </div>
          <div>
            <h4>Company</h4>
            <Link href="/contact">Contact</Link>
            <Link href="/privacy">Privacy policy</Link>
            <Link href="/terms">Terms of service</Link>
            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          </div>
        </div>
        <div className={styles.copy}>© {new Date().getFullYear()} RankPilot AI. No tool can guarantee rankings; RankPilot never does.</div>
      </div>
    </footer>
  );
}
