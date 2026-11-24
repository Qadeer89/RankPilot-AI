import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import styles from "@/components/site/site.module.css";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.wrap}>
      <SiteHeader />
      <main id="content">{children}</main>
      <SiteFooter />
    </div>
  );
}
