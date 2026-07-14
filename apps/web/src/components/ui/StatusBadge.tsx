import styles from "@/components/ui/StatusBadge.module.css";

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info";
export function StatusBadge({ tone = "neutral", children }: { tone?: StatusTone; children: string }) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
