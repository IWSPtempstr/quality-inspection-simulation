import type { ReactNode } from "react";
import styles from "@/components/ui/PageHeader.module.css";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return <header className={styles.header}><div><h1>{title}</h1>{description ? <p>{description}</p> : null}</div>{actions ? <div className={styles.actions}>{actions}</div> : null}</header>;
}
