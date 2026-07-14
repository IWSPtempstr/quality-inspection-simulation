import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleOff, CloudOff, Play, RefreshCw, SquareCheckBig } from "lucide-react";
import { apiRequest, createIdempotencyKey } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { Schedule, ScheduleStep } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";
import styles from "@/features/execution/ExecutionPage.module.css";

type ExecutionAction = "start" | "complete";
type StepAction = { id: string; version: number; action: ExecutionAction; idempotencyKey: string };

export function ExecutionPage() {
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const [feedback, setFeedback] = useState("");
  const [problem, setProblem] = useState<"conflict" | "degraded" | "offline" | "error" | null>(null);
  const [lastAction, setLastAction] = useState<StepAction | null>(null);
  const offline = useOfflineStatus();
  const schedule = useQuery({ queryKey: queryKeys.schedule, queryFn: () => apiRequest<Schedule>("/schedules/current") });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<{ status: "healthy" | "degraded" }>("/system/health") });
  const canExecute = can(session?.role, "execution:write");

  const report = useMutation({
    mutationFn: ({ id, version, action, idempotencyKey }: StepAction) => apiRequest<ScheduleStep>(`/schedule-steps/${id}/${action}`, { method: "PATCH", headers: { "If-Match": String(version), "Idempotency-Key": idempotencyKey } }),
    onSuccess: (updated, variables) => {
      queryClient.setQueryData<Schedule>(queryKeys.schedule, (current) => current ? { ...current, steps: current.steps.map((step) => step.id === updated.id ? updated : step) } : current);
      setFeedback(variables.action === "start" ? "服务端已确认开始，步骤状态已更新。" : "服务端已确认完成，步骤状态已更新。");
      setProblem(null);
      setLastAction(null);
    },
    onError: (error, variables) => {
      setLastAction(variables);
      setFeedback("");
      if (error instanceof ApiProblem && error.isConflict) setProblem("conflict");
      else if (error instanceof ApiProblem && error.isDegraded) setProblem("degraded");
      else if (!navigator.onLine || error instanceof TypeError) setProblem("offline");
      else setProblem("error");
    },
  });

  const refresh = async () => {
    setProblem(null);
    setFeedback("");
    await queryClient.invalidateQueries({ queryKey: queryKeys.schedule });
  };

  return <>
    <PageHeader title="执行报告" description="仅报告当前正式排程中的步骤。开始和完成均在服务端确认后更新。" />
    {offline ? <Guidance kind="offline" onRetry={() => void refresh()} /> : null}
    {!offline && health.data?.status === "degraded" ? <Guidance kind="degraded" onRetry={() => health.refetch()} /> : null}
    {health.isError ? <p className={styles.notice} role="status">服务健康状态暂不可用；请以当前已确认的排程数据为准。</p> : null}
    {feedback ? <p className={styles.success} role="status"><CheckCircle2 size={18} aria-hidden="true" />{feedback}</p> : null}
    {problem ? <Guidance kind={problem} onRetry={() => problem === "conflict" ? void refresh() : lastAction ? report.mutate(lastAction) : void refresh()} /> : null}
    <section className={styles.surface} aria-labelledby="assigned-steps-title">
      <div className={styles.sectionHeader}><div><h2 id="assigned-steps-title">当前正式排程</h2><p>操作前请核对设备、人员和计划时段。页面不会预先变更步骤状态。</p></div><span>排程版本 v{schedule.data?.version ?? "-"}</span></div>
      {schedule.isLoading ? <ExecutionSkeleton /> : schedule.isError ? <LoadError onRetry={() => schedule.refetch()} /> : !schedule.data?.steps.length ? <EmptyState /> : <div className={styles.tableWrap}><table><thead><tr><th scope="col">步骤</th><th scope="col">订单 / 项目</th><th scope="col">设备 / 人员</th><th scope="col">计划时段</th><th scope="col">状态</th><th scope="col"><span className="srOnly">执行操作</span></th></tr></thead><tbody>{schedule.data.steps.map((step) => <StepRow key={step.id} step={step} canExecute={canExecute} pending={report.isPending && report.variables?.id === step.id} onReport={(action) => { setFeedback(""); setProblem(null); report.mutate({ id: step.id, version: step.version, action, idempotencyKey: createIdempotencyKey() }); }} />)}</tbody></table></div>}
    </section>
  </>;
}

function StepRow({ step, canExecute, pending, onReport }: { step: ScheduleStep; canExecute: boolean; pending: boolean; onReport: (action: ExecutionAction) => void }) {
  const action = step.status === "scheduled" ? "start" : step.status === "running" ? "complete" : null;
  return <tr><td><strong>{step.id}</strong><small>版本 v{step.version}</small></td><td>{step.order_id}<small>{step.project_id}</small></td><td>{step.equipment_id ?? "未分配设备"}<small>{step.employee_ids.join("、") || "未分配人员"}</small></td><td>{formatRange(step.starts_at, step.ends_at)}</td><td><StatusBadge tone={stepTone(step.status)}>{stepLabel(step.status)}</StatusBadge>{step.frozen ? <small className={styles.frozen}>已冻结</small> : null}</td><td className={styles.actionCell}>{action && canExecute ? <Button type="button" onClick={() => onReport(action)} disabled={pending} aria-label={`${action === "start" ? "开始" : "完成"} ${step.id}`}>{pending ? "等待服务端确认" : action === "start" ? <><Play size={16} aria-hidden="true" />开始</> : <><SquareCheckBig size={16} aria-hidden="true" />完成</>}</Button> : <span className={styles.readOnly}>{canExecute ? "无需报告" : "无执行权限"}</span>}</td></tr>;
}

function Guidance({ kind, onRetry }: { kind: "conflict" | "degraded" | "offline" | "error"; onRetry: () => void }) {
  const copy = {
    conflict: ["执行步骤已发生版本冲突", "其他操作员或服务端已更新该步骤。请刷新当前排程，核对后再报告。", AlertTriangle, "刷新当前排程"],
    degraded: ["执行服务暂时降级", "请保留现场记录，稍后重试。当前步骤状态仍以最后一次服务端确认的结果为准。", CircleOff, "重试"],
    offline: ["当前处于离线状态", "不能提交开始或完成报告。恢复网络后刷新当前排程并重新确认。", CloudOff, "刷新当前排程"],
    error: ["执行报告未完成", "服务端未确认该操作，当前页面保留原有状态。请检查网络后重试。", AlertTriangle, "重试"],
  }[kind] as [string, string, typeof AlertTriangle, string];
  const Icon = copy[2];
  return <div className={`${styles.guidance} ${styles[kind]}`} role={kind === "conflict" || kind === "error" ? "alert" : "status"}><Icon size={19} aria-hidden="true" /><div><strong>{copy[0]}</strong><p>{copy[1]}</p></div><Button variant="secondary" type="button" onClick={onRetry} aria-label={copy[3]}><RefreshCw size={16} aria-hidden="true" />{copy[3]}</Button></div>;
}

function ExecutionSkeleton() { return <div className={styles.skeleton} aria-busy="true"><span /><span /><span /></div>; }
function LoadError({ onRetry }: { onRetry: () => void }) { return <div className={styles.loadError} role="alert"><AlertTriangle size={19} aria-hidden="true" /><div><strong>无法加载当前排程</strong><p>请检查网络后重试；未确认的执行操作不会写入页面。</p></div><Button variant="secondary" type="button" onClick={onRetry} aria-label="重试加载当前排程"><RefreshCw size={16} aria-hidden="true" />重试</Button></div>; }
function EmptyState() { return <div className={styles.empty}><CircleOff size={20} aria-hidden="true" />当前没有可报告的正式排程步骤。</div>; }

function useOfflineStatus() {
  const [offline, setOffline] = useState(() => !navigator.onLine);
  useEffect(() => { const sync = () => setOffline(!navigator.onLine); window.addEventListener("online", sync); window.addEventListener("offline", sync); return () => { window.removeEventListener("online", sync); window.removeEventListener("offline", sync); }; }, []);
  return offline;
}

const formatRange = (start: string, end: string) => `${formatTime(start)} - ${formatTime(end)}`;
const formatTime = (value: string) => new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
const stepLabel = (status: string) => ({ scheduled: "已计划", running: "进行中", completed: "已完成", blocked: "已阻塞" }[status] ?? status);
const stepTone = (status: string): StatusTone => status === "completed" ? "success" : status === "running" ? "info" : status === "blocked" ? "danger" : "neutral";
