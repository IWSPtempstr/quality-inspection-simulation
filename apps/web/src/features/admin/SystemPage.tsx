import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CloudOff, FileWarning, RefreshCw, ServerCrash } from "lucide-react";
import { apiRequest } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Health } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import styles from "@/features/admin/AdminPages.module.css";

export function SystemPage() {
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<Health>("/system/health") });
  return <><PageHeader title="系统状态" description="服务健康状态仅供观察，所有修复和控制操作在此工作台之外执行。" />{health.isLoading ? <section className={styles.state} aria-busy="true">正在检查系统状态…</section> : health.isError ? <section className={styles.offline} role="alert"><CloudOff size={20} aria-hidden="true" /><div><strong>无法读取系统状态</strong><p>健康检查服务暂不可用。请检查网络后重试。</p></div><Button variant="secondary" type="button" onClick={() => health.refetch()} aria-label="重试加载系统状态"><RefreshCw size={16} aria-hidden="true" />重试</Button></section> : health.data ? <SystemHealth health={health.data} /> : null}</>;
}

function SystemHealth({ health }: { health: Health }) {
  const degraded = health.status === "degraded";
  return <><section className={degraded ? styles.degraded : styles.healthy} role="status">{degraded ? <FileWarning size={20} aria-hidden="true" /> : <CheckCircle2 size={20} aria-hidden="true" />}<div><strong>{degraded ? "部分服务降级" : "系统服务正常"}</strong><p>{degraded ? "标准查询可能证据不足" : "当前服务状态由服务端健康检查确认。"}</p>{degraded ? <small>请核对引用后再作出人工判断。</small> : null}</div></section><section className={styles.surface} aria-labelledby="services-title"><div className={styles.heading}><div><h2 id="services-title">服务清单</h2><p>只读显示健康检查返回的组件状态。</p></div></div>{Object.keys(health.services).length ? <ul className={styles.services}>{Object.entries(health.services).map(([name, status]) => <li key={name}><span><ServerCrash size={17} aria-hidden="true" /><strong>{name}</strong></span><span className={status === "healthy" ? styles.serviceHealthy : styles.serviceDegraded}>{status === "healthy" ? "正常" : "降级"}</span></li>)}</ul> : <div className={styles.state}>服务端未返回组件状态。</div>}</section></>;
}
