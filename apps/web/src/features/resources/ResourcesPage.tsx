import { useState, type ReactNode } from "react";
import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { FileSearch, Filter, RotateCcw, Search } from "lucide-react";
import { apiRequest } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataQualityPreflight, Employee, Equipment, Health, Shift, Unavailability } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";
import styles from "@/features/resources/ResourcesPage.module.css";

type ResourceQuery<T> = UseQueryResult<T[]>;

export function ResourcesPage() {
  const session = useSessionStore((state) => state.session);
  const canPreflight = can(session?.role, "schedule:write");
  const [preflight, setPreflight] = useState<DataQualityPreflight | null>(null);
  const equipment = useQuery({ queryKey: [...queryKeys.resources, "equipment"], queryFn: () => apiRequest<Equipment[]>("/resources/equipment") });
  const employees = useQuery({ queryKey: [...queryKeys.resources, "employees"], queryFn: () => apiRequest<Employee[]>("/resources/employees") });
  const shifts = useQuery({ queryKey: [...queryKeys.resources, "shifts"], queryFn: () => apiRequest<Shift[]>("/resources/shifts") });
  const unavailability = useQuery({ queryKey: [...queryKeys.resources, "unavailability"], queryFn: () => apiRequest<Unavailability[]>("/resources/unavailability") });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<Health>("/system/health") });
  const check = useMutation({ mutationFn: () => apiRequest<DataQualityPreflight>("/schedule-previews/preflight", { method: "POST", body: JSON.stringify({ scope: "resource" }) }), onSuccess: setPreflight });

  return <>
    <PageHeader title="资源" description="查看设备、人员班次与不可用时段。资源信息由已确认的服务端记录提供。" />
    {health.data?.status === "degraded" ? <p className={styles.degraded} role="status" aria-label="资源服务提示">部分辅助服务降级；资源清单仍为只读服务端数据。</p> : null}
    {health.isError ? <p className={styles.healthError} role="status">服务健康状态暂不可用，资源数据仍可单独查看。</p> : null}
    {canPreflight ? <section className={styles.preflight} aria-labelledby="resource-preflight-title"><div><h2 id="resource-preflight-title">资源数据预检</h2><p>规则校验设备适用性、容量、人员技能、班次和不可用窗口；助手只解释结果。</p></div><Button variant="secondary" type="button" onClick={() => check.mutate()} disabled={check.isPending}><FileSearch size={16} aria-hidden="true" />{check.isPending ? "正在检查" : "检查资源数据"}</Button>{preflight ? <div className={styles.preflightResult} role={preflight.status === "blocked" ? "alert" : "status"}>{preflight.findings.map((finding) => <p key={finding.code}><strong>{finding.blocking ? "阻塞：" : "提示："}</strong>{finding.message}{finding.suggestion ? ` ${finding.suggestion}` : ""}</p>)}</div> : null}</section> : null}
    <div className={styles.grid}>
      <EquipmentSurface query={equipment} />
      <EmployeeSurface query={employees} />
      <ShiftSurface query={shifts} />
      <UnavailabilitySurface query={unavailability} />
    </div>
  </>;
}

function EquipmentSurface({ query }: { query: ResourceQuery<Equipment> }) {
  return <ResourceSurface title="设备" description="按编号、名称或状态筛选。" query={query} searchLabel="筛选设备" matches={(item, term) => [item.id, item.name, item.status, ...item.project_ids].some((value) => contains(value, term))} columns={<><th>设备编号</th><th>设备名称</th><th>状态</th><th>容量</th><th>支持项目</th><th>版本</th></>} renderRow={(item) => <tr key={item.id}><td>{item.id}</td><td><strong>{item.name}</strong></td><td><StatusBadge tone={resourceTone(item.status)}>{statusLabel(item.status)}</StatusBadge></td><td>{item.capacity}</td><td>{item.project_ids.join(" / ")}</td><td>v{item.version}</td></tr>} />;
}

function EmployeeSurface({ query }: { query: ResourceQuery<Employee> }) {
  return <ResourceSurface title="人员" description="按工号、姓名、技能或班次筛选。" query={query} searchLabel="筛选人员" matches={(item, term) => [item.id, item.name, item.shift_id ?? "未分配", ...item.skills].some((value) => contains(value, term))} columns={<><th>人员编号</th><th>姓名</th><th>技能</th><th>班次</th><th>版本</th></>} renderRow={(item) => <tr key={item.id}><td>{item.id}</td><td><strong>{item.name}</strong></td><td>{item.skills.join(" / ")}</td><td>{item.shift_id ?? "未分配"}</td><td>v{item.version}</td></tr>} />;
}

function ShiftSurface({ query }: { query: ResourceQuery<Shift> }) {
  return <ResourceSurface title="班次" description="按班次编号、名称或时间筛选。" query={query} searchLabel="筛选班次" matches={(item, term) => [item.id, item.name, item.start_time, item.end_time].some((value) => contains(value, term))} columns={<><th>班次编号</th><th>班次名称</th><th>开始时间</th><th>结束时间</th></>} renderRow={(item) => <tr key={item.id}><td>{item.id}</td><td><strong>{item.name}</strong></td><td>{item.start_time}</td><td>{item.end_time}</td></tr>} />;
}

function UnavailabilitySurface({ query }: { query: ResourceQuery<Unavailability> }) {
  return <ResourceSurface title="不可用时段" description="按资源、原因或时间扫描。" query={query} searchLabel="筛选不可用时段" matches={(item, term) => [item.id, item.entity_id, item.reason ?? "未说明", item.starts_at, item.ends_at].some((value) => contains(value, term))} columns={<><th>记录编号</th><th>资源编号</th><th>开始时间</th><th>结束时间</th><th>原因</th></>} renderRow={(item) => <tr key={item.id}><td>{item.id}</td><td>{item.entity_id}</td><td>{formatDate(item.starts_at)}</td><td>{formatDate(item.ends_at)}</td><td>{item.reason ?? "未说明"}</td></tr>} />;
}

function ResourceSurface<T extends { id: string }>({ title, description, query, searchLabel, matches, columns, renderRow }: { title: string; description: string; query: ResourceQuery<T>; searchLabel: string; matches: (item: T, term: string) => boolean; columns: ReactNode; renderRow: (item: T) => ReactNode }) {
  const [term, setTerm] = useState("");
  const visibleItems = (query.data ?? []).filter((item) => matches(item, term));
  const titleId = `${title}-title`;
  return <section className={styles.surface} role="region" aria-labelledby={titleId}>
    <div className={styles.surfaceHeader}>
      <div><h2 id={titleId}>{title}</h2><p>{description}</p></div>
      <label className={styles.search}><Search size={16} aria-hidden="true" /><input value={term} onChange={(event) => setTerm(event.target.value)} placeholder={searchLabel} aria-label={searchLabel} /></label>
    </div>
    {query.isLoading ? <TableSkeleton title={title} /> : query.isError ? <TableError title={title} onRetry={() => query.refetch()} /> : visibleItems.length ? <div className={styles.tableWrap}><table><thead><tr>{columns}</tr></thead><tbody>{visibleItems.map(renderRow)}</tbody></table></div> : <EmptyState title={title} hasFilter={Boolean(term)} />}
  </section>;
}

function TableSkeleton({ title }: { title: string }) { return <div className={styles.tableState} aria-busy="true"><RotateCcw size={18} aria-hidden="true" />正在加载{title}…</div>; }
function TableError({ title, onRetry }: { title: string; onRetry: () => void }) { return <div className={styles.tableState} role="alert"><span>无法加载{title}。请检查网络后重试。</span><Button variant="secondary" type="button" onClick={onRetry} aria-label={`重试加载${title}`}><RotateCcw size={16} aria-hidden="true" />重试</Button></div>; }
function EmptyState({ title, hasFilter }: { title: string; hasFilter: boolean }) { return <div className={styles.tableState}><Filter size={18} aria-hidden="true" />{hasFilter ? `没有符合筛选条件的${title}。` : `暂无${title}记录。`}</div>; }

const contains = (value: string, term: string) => value.toLowerCase().includes(term.trim().toLowerCase());
const formatDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
const statusLabel = (status: string) => ({ available: "可用", running: "运行中", maintenance: "维护中", unavailable: "不可用" }[status] ?? status);
const resourceTone = (status: string): StatusTone => status === "available" ? "success" : status === "maintenance" || status === "unavailable" ? "warning" : "info";
