import Link from "next/link";
import styles from "./page.module.css";

export default function Home() {
  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>RankPilot AI</h1>
        <p>
          Give us your website. We&apos;ll continuously find, implement and validate SEO
          improvements.
        </p>
        <div className={styles.ctas}>
          <Link className={styles.primary} href="/register">
            Create an account
          </Link>
          <Link className={styles.secondary} href="/login">
            Log in
          </Link>
        </div>
      </main>
    </div>
  );
}
