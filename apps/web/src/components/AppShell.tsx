"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { MeResponse, getMe } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import styles from "./AppShell.module.css";

const NAV_ITEMS = [{ href: "/dashboard", label: "Websites" }];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    getMe(token)
      .then(setMe)
      .catch(() => {
        // Each page already redirects to /login on an invalid session;
        // the shell just has nothing to show in the account menu here.
      });
  }, []);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  const orgName = me?.organizations[0]?.name;

  return (
    <div className={styles.shell}>
      {drawerOpen && (
        <div className={styles.scrim} onClick={() => setDrawerOpen(false)} aria-hidden="true" />
      )}

      <aside className={`${styles.sidebar} ${drawerOpen ? styles.sidebarOpen : ""}`}>
        <Link href="/dashboard" className={styles.brand} onClick={() => setDrawerOpen(false)}>
          RankPilot <span className={styles.brandAccent}>AI</span>
        </Link>

        <nav className={styles.nav} aria-label="Primary">
          <p className={styles.navGroupLabel}>Workspace</p>
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`${styles.navLink} ${active ? styles.navLinkActive : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={() => setDrawerOpen(false)}
              >
                {item.label}
              </Link>
            );
          })}

          {orgName && (
            <Link
              href="/dashboard/organization"
              className={`${styles.navLink} ${pathname === "/dashboard/organization" ? styles.navLinkActive : ""}`}
              aria-current={pathname === "/dashboard/organization" ? "page" : undefined}
              onClick={() => setDrawerOpen(false)}
            >
              Agency overview
            </Link>
          )}
        </nav>

        {me && (
          <div className={styles.sidebarFooter}>
            <div className={styles.sidebarOrg}>{orgName ?? "Workspace"}</div>
            <div className={styles.sidebarEmail}>{me.user.email}</div>
            <button type="button" className={styles.logoutButton} onClick={handleLogout}>
              Log out
            </button>
          </div>
        )}
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <button
            type="button"
            className={styles.menuButton}
            aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen((v) => !v)}
          >
            <span className={styles.menuIcon} aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
          </button>
          <span className={styles.topbarBrandMobile}>RankPilot AI</span>
        </header>
        <div className={styles.content}>{children}</div>
      </div>
    </div>
  );
}
