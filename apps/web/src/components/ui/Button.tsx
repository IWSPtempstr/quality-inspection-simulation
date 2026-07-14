import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "@/components/ui/Button.module.css";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export function Button({ variant = "primary", children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; children: ReactNode }) {
  return <button className={`${styles.button} ${styles[variant]} ${className}`} {...props}>{children}</button>;
}
