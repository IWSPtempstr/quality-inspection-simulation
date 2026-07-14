import { Construction } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import styles from "@/app/PlaceholderPage.module.css";

export function PlaceholderPage({ title }: { title: string }) {
  return <><PageHeader title={title} description="此业务页面将在后续前端任务中接入固定 Mock 数据和完整交互。" /><section className={styles.empty}><Construction aria-hidden="true" size={24} /><p>页面准备中</p></section></>;
}
