"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { getToken } from "@/lib/auth";
import styles from "./site.module.css";

const LINKS = [
  { href: "/features", label: "Features" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/pricing", label: "Pricing" },
  { href: "/faq", label: "FAQ" },
];

export default function SiteHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  // Server render and first paint assume signed out; the browser then reads the stored token (no state set inside an effect).
  const signedIn = useSyncExternalStore(
    () => () => {},
    () => { try { return Boolean(getToken()); } catch { return false; } },
    () => false,
  );
  return (
    <header className={styles.header}>
      <div className={`${styles.container} ${styles.nav}`}>
        <Link href="/" className={styles.brand}>RankPilot <span>AI</span></Link>
        <nav className={styles.links} aria-label="Main">
          {LINKS.map((l) => <Link key={l.href} href={l.href} aria-current={pathname === l.href ? "page" : undefined} className={pathname === l.href ? styles.active : undefined}>{l.label}</Link>)}
        </nav>
        <div className={styles.navActions}>
          {signedIn ? (
            <Link href="/dashboard" className={`${styles.btn} ${styles.btnPrimary}`}>Open dashboard</Link>
          ) : (
            <>
              <Link href="/login" className={`${styles.btn} ${styles.btnGhost}`}>Log in</Link>
              <Link href="/register" className={`${styles.btn} ${styles.btnPrimary}`}>Start free</Link>
            </>
          )}
          <button type="button" className={styles.menuButton} aria-expanded={open} aria-controls="mobile-menu" onClick={() => setOpen(!open)}>
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>
      <nav id="mobile-menu" aria-label="Mobile" className={`${styles.mobileMenu} ${open ? styles.open : ""}`}>
        {LINKS.map((l) => <Link key={l.href} href={l.href} onClick={() => setOpen(false)}>{l.label}</Link>)}
        {!signedIn && <Link href="/login" onClick={() => setOpen(false)}>Log in</Link>}
      </nav>
    </header>
  );
}
