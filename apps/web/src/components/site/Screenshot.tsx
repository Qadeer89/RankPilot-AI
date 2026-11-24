import Image from "next/image";
import styles from "./site.module.css";

// Real application pages rendered with sample data for a fictional site (see e2e/capture-marketing.spec.ts).
const SIZES: Record<string, [number, number]> = {
  overview: [1360, 860], findings: [1360, 860], "growth-plan": [1360, 860], authority: [1360, 900], intelligence: [1360, 900], history: [1360, 900], keywords: [1360, 900],
};

export default function Screenshot({ name, alt, caption, priority = false }: { name: keyof typeof SIZES | string; alt: string; caption?: string; priority?: boolean }) {
  const [w, h] = SIZES[name] ?? [1360, 860];
  return (
    <figure className={styles.shot}>
      <div className={styles.shotFrame}>
        <div className={styles.shotBar} aria-hidden="true"><i /><i /><i /></div>
        <Image src={`/screens/${name}.jpg`} alt={alt} width={w} height={h} sizes="(max-width: 900px) 100vw, 1120px" priority={priority} />
      </div>
      <figcaption>{caption && <span>{caption} </span>}<em>Sample data for a fictional site.</em></figcaption>
    </figure>
  );
}
