import styles from "./EmptyState.module.css";

export default function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className={styles.empty}>
      <span className={styles.title}>{title}</span>
      {description && <span className={styles.description}>{description}</span>}
    </div>
  );
}
