import { LockKeyhole } from "lucide-react";
import styles from "@/components/ui/PermissionDenied.module.css";

export function PermissionDenied() { return <section className={styles.state}><LockKeyhole aria-hidden="true" size={28} /><h2>无权访问此页面</h2><p>当前角色没有执行此操作的权限。</p></section>; }
