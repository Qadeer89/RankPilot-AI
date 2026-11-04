import styles from "./MetricCard.module.css";

export interface Metric {
  label: string;
  value: number | string;
  meta?: string;
  attention?: boolean;
}

export function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <div className={styles.grid}>
      {metrics.map((m) => (
        <div className={styles.tile} key={m.label}>
          <span className={styles.label}>{m.label}</span>
          <span className={`${styles.value} ${m.attention ? styles.valueAttention : ""}`}>{m.value}</span>
          {m.meta && <span className={styles.meta}>{m.meta}</span>}
        </div>
      ))}
    </div>
  );
}
