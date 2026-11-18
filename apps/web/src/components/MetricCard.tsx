import styles from "./MetricCard.module.css";

export interface Metric {
  label: string;
  value: number | string;
  meta?: string;
  attention?: boolean;
  /** When set, the tile is a button that takes the person to the matching list. */
  onClick?: () => void;
  hint?: string;
}

export function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <div className={styles.grid}>
      {metrics.map((m) => (
        m.onClick ? (
          <button type="button" className={`${styles.tile} ${styles.tileButton}`} key={m.label} onClick={m.onClick} title={m.hint}>
            <span className={styles.label}>{m.label}</span>
            <span className={`${styles.value} ${m.attention ? styles.valueAttention : ""}`}>{m.value}</span>
            {m.meta && <span className={styles.meta}>{m.meta}</span>}
            <span className={styles.go} aria-hidden="true">{m.hint ?? "View"} →</span>
          </button>
        ) : (
          <div className={styles.tile} key={m.label}>
            <span className={styles.label}>{m.label}</span>
            <span className={`${styles.value} ${m.attention ? styles.valueAttention : ""}`}>{m.value}</span>
            {m.meta && <span className={styles.meta}>{m.meta}</span>}
          </div>
        )
      ))}
    </div>
  );
}
