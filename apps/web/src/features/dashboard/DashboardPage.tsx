import { useQueries } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CircleCheck, Clock3, Wrench } from "lucide-react";
import { apiRequest } from "@/api/client";
import type { Event, Order, Page, SchedulePreview } from "@/api/types";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import styles from "@/features/dashboard/DashboardPage.module.css";

const request = <T,>(path: string) => () => apiRequest<T>(path);

export function DashboardPage() {
  const [orders, events, previews] = useQueries({ queries: [
    { queryKey: ["dashboard", "orders"], queryFn: request<Page<Order>>("/orders") },
    { queryKey: ["dashboard", "events"], queryFn: request<Page<Event>>("/events") },
    { queryKey: ["dashboard", "previews"], queryFn: request<Page<SchedulePreview>>("/schedule-previews") },
  ] });
  const loading = orders.isLoading || events.isLoading || previews.isLoading;
  const failed = orders.isError || events.isError || previews.isError;
  const items = orders.data?.items ?? [];
  const openEvents = events.data?.items.filter((event) => event.status === "open") ?? [];
  const preview = previews.data?.items.find((item) => item.status === "pending_review");
  const lateCount = items.filter((order) => order.status === "blocked").length;

  return <>
    <PageHeader title="总览" description="以当前正式排程、候选变更和未闭环事件为准。" />
    {failed ? <section className={styles.problem}><AlertTriangle aria-hidden="true" /><div><strong>部分数据无法加载</strong><p>正式排程未受影响。请检查网络或稍后重试。</p><Button variant="secondary" type="button" onClick={() => { orders.refetch(); events.refetch(); previews.refetch(); }}>重试</Button></div></section> : null}
    <section className={styles.metrics} aria-label="当前运营状态">
      <Metric icon={<CalendarClock />} label="待审批候选" value={loading ? "-" : preview ? "1" : "0"} detail={preview ? `${preview.changed_step_count} 个步骤变更` : "暂无候选"} />
      <Metric icon={<AlertTriangle />} label="待处理事件" value={loading ? "-" : String(openEvents.length)} detail={openEvents[0]?.event_type ?? "暂无事件"} tone="warning" />
      <Metric icon={<Clock3 />} label="阻塞订单" value={loading ? "-" : String(lateCount)} detail="需处理资源或异常约束" tone={lateCount ? "danger" : "neutral"} />
      <Metric icon={<CircleCheck />} label="当前算法" value={loading ? "-" : preview?.algorithm_used === "sla_fallback" ? "SLA 兜底" : "CP-SAT"} detail={preview?.solver_status ?? "正式排程稳定"} tone="info" />
    </section>
    <section className={styles.grid}>
      <section className={styles.surface} aria-labelledby="event-heading"><div className={styles.sectionHeading}><div><h2 id="event-heading">优先处理事件</h2><p>影响候选排程前必须完成事实确认。</p></div><Wrench aria-hidden="true" /></div>{loading ? <Rows count={3} /> : openEvents.length ? <div className={styles.list}>{openEvents.map((event) => <article className={styles.listRow} key={event.id}><div><strong>{event.event_type}</strong><span>{event.entity_id ?? "未关联对象"}</span></div><StatusBadge tone={event.severity === "high" ? "danger" : "warning"}>{event.severity === "high" ? "高优先级" : "处理中"}</StatusBadge></article>)}</div> : <Empty message="当前没有待处理事件。" />}</section>
      <section className={styles.surface} aria-labelledby="preview-heading"><div className={styles.sectionHeading}><div><h2 id="preview-heading">候选排程</h2><p>候选不会自动成为正式排程。</p></div></div>{loading ? <Rows count={3} /> : preview ? <div className={styles.preview}><dl><div><dt>基础版本</dt><dd>v{preview.base_schedule_version}</dd></div><div><dt>冻结步骤</dt><dd>{preview.frozen_step_count}</dd></div><div><dt>预计延期</dt><dd>{preview.total_delay_minutes} 分钟</dd></div></dl><StatusBadge tone={preview.fallback_used ? "warning" : "info"}>{preview.fallback_used ? "SLA 兜底" : "CP-SAT 可行解"}</StatusBadge></div> : <Empty message="暂无等待审批的候选排程。" />}</section>
    </section>
  </>;
}

function Metric({ icon, label, value, detail, tone = "neutral" }: { icon: React.ReactNode; label: string; value: string; detail: string; tone?: "neutral" | "warning" | "danger" | "info" }) { return <article className={`${styles.metric} ${styles[tone]}`}><span className={styles.metricIcon} aria-hidden="true">{icon}</span><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>; }
function Empty({ message }: { message: string }) { return <div className={styles.empty}>{message}</div>; }
function Rows({ count }: { count: number }) { return <div className={styles.skeletons}>{Array.from({ length: count }, (_, index) => <span key={index} />)}</div>; }
