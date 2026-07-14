import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock3, FileSearch, LockKeyhole, RefreshCw, Sparkles, XCircle } from "lucide-react";
import { apiRequest, createIdempotencyKey } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { DataQualityPreflight, Page, Schedule, ScheduleExplanation, SchedulePreview, ScheduleStep } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";
import styles from "@/features/scheduling/SchedulingPage.module.css";

type ReviewAction = "approve" | "reject";

export function SchedulingPage() {
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const canReview = can(session?.role, "schedule:write");
  const schedule = useQuery({ queryKey: queryKeys.schedule, queryFn: () => apiRequest<Schedule>("/schedules/current") });
  const previews = useQuery({ queryKey: queryKeys.previews, queryFn: () => apiRequest<Page<SchedulePreview>>("/schedule-previews") });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<{ status: "healthy" | "degraded" }>("/system/health") });
  const [confirmedPreview, setConfirmedPreview] = useState<SchedulePreview | null>(null);
  const [feedback, setFeedback] = useState("");
  const [conflict, setConflict] = useState(false);
  const [confirming, setConfirming] = useState<ReviewAction | null>(null);
  const [explanation, setExplanation] = useState<ScheduleExplanation | null>(null);
  const [preflight, setPreflight] = useState<DataQualityPreflight | null>(null);
  const reviewOperationKeys = useRef<Record<string, string>>({});
  const rejectTrigger = useRef<HTMLElement | null>(null);
  const preview = confirmedPreview ?? previews.data?.items.find((item) => item.status === "pending_review") ?? previews.data?.items[0];

  useEffect(() => {
    if (confirming === null && rejectTrigger.current) {
      rejectTrigger.current.focus();
      rejectTrigger.current = null;
    }
  }, [confirming]);

  const refresh = async (clearConflict = true) => {
    if (clearConflict) setConflict(false);
    setConfirmedPreview(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.schedule }),
      queryClient.invalidateQueries({ queryKey: queryKeys.previews }),
    ]);
  };

  const review = useMutation({
    mutationFn: async (action: ReviewAction) => {
      if (!preview) throw new Error("没有可处理的候选排程");
      const operation = reviewOperationKey(preview, action);
      const idempotencyKey = reviewOperationKeys.current[operation] ?? (reviewOperationKeys.current[operation] = createIdempotencyKey());
      return apiRequest<SchedulePreview>(`/schedule-previews/${preview.id}/${action}`, { method: "POST", headers: { "If-Match": String(preview.version), "Idempotency-Key": idempotencyKey } });
    },
    onSuccess: async (result, action) => {
      if (preview) delete reviewOperationKeys.current[reviewOperationKey(preview, action)];
      setConfirmedPreview(result);
      setFeedback(action === "approve" ? "候选排程已获批准，服务端已确认。" : "候选排程已被拒绝，服务端已确认。");
      setConfirming(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.schedule });
    },
    onError: async (error, action) => {
      setConfirming(null);
      if (error instanceof ApiProblem && error.isConflict) {
        if (preview) delete reviewOperationKeys.current[reviewOperationKey(preview, action)];
        setConflict(true);
        await refresh(false);
        return;
      }
      setFeedback(error instanceof Error ? `操作未完成：${error.message}` : "操作未完成，请稍后重试。");
    },
  });
  const explain = useMutation({
    mutationFn: (current: SchedulePreview) => apiRequest<ScheduleExplanation>(`/schedule-previews/${current.id}/explanation`, { method: "POST", body: JSON.stringify({ subject_type: "preview", subject_id: current.id }) }),
    onSuccess: setExplanation,
  });
  const runPreflight = useMutation({
    mutationFn: () => apiRequest<DataQualityPreflight>("/schedule-previews/preflight", { method: "POST", body: JSON.stringify({ scope: "schedule_preview", preview_id: preview?.id }) }),
    onSuccess: setPreflight,
  });

  const openRejectConfirmation = (trigger: HTMLElement) => {
    rejectTrigger.current = trigger;
    setConfirming("reject");
  };

  const loading = schedule.isLoading || previews.isLoading;
  return <>
    <PageHeader title="排程工作台" description="查看已确认排程与服务端生成的候选变更；所有审批结果以服务端确认状态为准。" />
    {health.data?.status === "degraded" ? <p className={styles.degraded} role="status">辅助服务降级中；当前排程与候选结果仍为服务端只读数据。</p> : null}
    {health.isError ? <p className={styles.healthError} role="status">服务健康状态暂不可用，排程数据仍可单独查看。</p> : null}
    {feedback ? <p className={styles.feedback} role="status"><CheckCircle2 size={17} aria-hidden="true" />{feedback}</p> : null}
    {conflict ? <div className={styles.conflict} role="alert"><AlertTriangle size={18} aria-hidden="true" /><div><strong>候选排程已发生版本冲突</strong><p>其他调度员或服务端状态已更新。已刷新候选信息，请确认后再处理。</p></div><Button variant="secondary" type="button" onClick={() => void refresh()} aria-label="刷新候选排程"><RefreshCw size={16} aria-hidden="true" />刷新</Button></div> : null}
    {loading ? <WorkbenchSkeleton /> : <main className={styles.workbench}>
      <section className={styles.timelineSection} aria-labelledby="timeline-title">
        <div className={styles.sectionHeading}><div><h2 id="timeline-title">当前排程</h2><p>按设备查看已确认步骤。锁定图标表示运行中或不可变更的冻结步骤。</p></div><span>版本 v{schedule.data?.version ?? "-"}</span></div>
        {schedule.isError ? <LoadError label="当前排程" onRetry={() => schedule.refetch()} /> : <GanttTimeline steps={schedule.data?.steps ?? []} />}
      </section>
      <aside className={styles.sidePanel} aria-label="候选排程详情">
        {previews.isError ? <LoadError label="候选排程" onRetry={() => previews.refetch()} /> : !preview ? <EmptyPreview /> : <PreviewReview preview={preview} canReview={canReview} pending={review.isPending} locked={confirming !== null} explanation={explanation} preflight={preflight} explanationPending={explain.isPending} preflightPending={runPreflight.isPending} onExplain={() => explain.mutate(preview)} onPreflight={() => runPreflight.mutate()} onApprove={() => review.mutate("approve")} onReject={openRejectConfirmation} />}
      </aside>
    </main>}
    {confirming && preview ? <RejectConfirmation pending={review.isPending} onCancel={() => setConfirming(null)} onConfirm={() => review.mutate("reject")} /> : null}
  </>;
}

function GanttTimeline({ steps }: { steps: ScheduleStep[] }) {
  if (!steps.length) return <div className={styles.empty}><Clock3 size={20} aria-hidden="true" />当前排程暂无步骤。</div>;
  const equipment = [...new Set(steps.map((step) => step.equipment_id ?? "未分配设备"))];
  const starts = steps.map((step) => new Date(step.starts_at).getTime());
  const ends = steps.map((step) => new Date(step.ends_at).getTime());
  const start = Math.min(...starts);
  const end = Math.max(...ends);
  const range = Math.max(end - start, 1);
  const labels = Array.from({ length: 5 }, (_, index) => formatTime(start + (range * index) / 4));
  return <div className={styles.gantt} role="region" aria-label="当前排程甘特图">
    <div className={styles.ganttHeader}><span>设备</span><div>{labels.map((label) => <span key={label}>{label}</span>)}</div></div>
    {equipment.map((equipmentId) => <div className={styles.ganttRow} key={equipmentId}><strong>{equipmentId}</strong><div className={styles.track}>{steps.filter((step) => (step.equipment_id ?? "未分配设备") === equipmentId).map((step) => <StepBar key={step.id} step={step} start={start} range={range} />)}</div></div>)}
  </div>;
}

function StepBar({ step, start, range }: { step: ScheduleStep; start: number; range: number }) {
  const left = ((new Date(step.starts_at).getTime() - start) / range) * 100;
  const width = Math.max(((new Date(step.ends_at).getTime() - new Date(step.starts_at).getTime()) / range) * 100, 8);
  return <div className={`${styles.stepBar} ${step.frozen ? styles.frozen : ""}`} style={{ left: `${left}%`, width: `${width}%` }} title={`${step.id}：${step.frozen ? "已冻结" : "可查看"}`}><span>{step.frozen ? <LockKeyhole size={13} aria-hidden="true" /> : null}{step.id}</span>{step.frozen ? <small>运行中，已冻结</small> : null}</div>;
}

function PreviewReview({ preview, canReview, pending, locked, explanation, preflight, explanationPending, preflightPending, onExplain, onPreflight, onApprove, onReject }: { preview: SchedulePreview; canReview: boolean; pending: boolean; locked: boolean; explanation: ScheduleExplanation | null; preflight: DataQualityPreflight | null; explanationPending: boolean; preflightPending: boolean; onExplain: () => void; onPreflight: () => void; onApprove: () => void; onReject: (trigger: HTMLElement) => void }) {
  return <>
    <div className={styles.reviewContent}>
      <section className={styles.previewSection} aria-labelledby="candidate-title">
        <div className={styles.sectionHeading}><div><h2 id="candidate-title">候选排程</h2><p>{preview.id} · 基准排程 v{preview.base_schedule_version}</p></div><StatusBadge tone={previewTone(preview.status)}>{previewStatus(preview.status)}</StatusBadge></div>
        <ul className={styles.metrics} aria-label="候选排程指标">
          <Metric label="算法" value={preview.algorithm_used === "cp_sat" ? "CP-SAT" : "SLA 兜底"} note={preview.solver_status} />
          <Metric label="冻结步骤" value={`${preview.frozen_step_count} 个`} note="保持不变" />
          <Metric label="变更步骤" value={`${preview.changed_step_count} 个`} note="候选影响" />
          <Metric label="延误订单" value={`${preview.delayed_order_count} 单`} note="需关注 SLA" />
          <Metric label="加权延误" value={`${preview.weighted_delay_minutes} 分钟`} note="按优先级计算" />
          <Metric label="总延误" value={`${preview.total_delay_minutes} 分钟`} note="候选结果" />
        </ul>
        <div className={styles.assistanceActions}><Button variant="secondary" type="button" onClick={onExplain} disabled={explanationPending}><Sparkles size={16} aria-hidden="true" />{explanationPending ? "正在生成说明" : "查看排程说明"}</Button>{canReview ? <Button variant="secondary" type="button" onClick={onPreflight} disabled={preflightPending}><FileSearch size={16} aria-hidden="true" />{preflightPending ? "正在检查" : "排程前检查"}</Button> : null}</div>
      </section>
      {explanation ? <section className={styles.assistancePanel} aria-labelledby="explanation-title"><h2 id="explanation-title">排程说明</h2><p>{explanation.summary}</p><AssistanceList title="约束依据" values={explanation.constraint_reasons} /><AssistanceList title="目标权衡" values={explanation.tradeoffs} /><p className={styles.assistanceMeta}>冻结步骤：{explanation.frozen_step_ids.join(" / ") || "无"}。{explanation.degraded ? "当前辅助服务降级，结果仅供复核。" : "说明不触发重排或审批。"}</p></section> : null}
      {preflight ? <section className={styles.assistancePanel} aria-labelledby="preflight-title"><h2 id="preflight-title">排程前检查</h2><p>{preflight.status === "blocked" ? "发现阻塞问题，候选不能绕过确定性校验。" : "未发现阻塞问题。"}</p><ul className={styles.findingList}>{preflight.findings.map((finding) => <li key={finding.code}><strong>{finding.blocking ? "阻塞" : "提示"}</strong><span>{finding.message}</span>{finding.suggestion ? <small>{finding.suggestion}</small> : null}</li>)}</ul><p className={styles.assistanceMeta}>{preflight.degraded ? "解释服务降级；以上确定性检查仍有效。" : "AI 仅解释规则，不会修正数据或选择资源。"}</p></section> : null}
      {preview.fallback_used ? <FallbackContext reason={preview.fallback_reason} /> : null}
      <BlockerList blockers={preview.blockers} />
      <section className={styles.diffSection} aria-labelledby="diff-title">
        <h2 id="diff-title">变更对比</h2>
        {preview.changes.length ? <ul className={styles.diffList}>{preview.changes.map((change, index) => <li key={`${String(change.step_id ?? index)}-${index}`}><strong>{String(change.step_id ?? "步骤")}</strong><span>{change.type === "moved" ? "调整" : String(change.type ?? "变更")}</span><small>{formatChangeTime(change.from)} 至 {formatChangeTime(change.to)}</small></li>)}</ul> : <p className={styles.emptyDiff}>候选排程没有步骤变更。</p>}
      </section>
    </div>
    {canReview && preview.status === "pending_review" ? <div className={styles.reviewActions}><Button type="button" onClick={onApprove} disabled={pending || locked} aria-label="批准候选排程">{pending ? "正在等待服务端确认…" : "批准"}</Button><Button variant="danger" type="button" onClick={(event) => onReject(event.currentTarget)} disabled={pending || locked} aria-label="拒绝候选排程">拒绝</Button></div> : <p className={styles.readOnly} role="status">{canReview ? "该候选排程无需再处理。" : "候选排程为只读；当前角色没有审批权限。"}</p>}
  </>;
}

function FallbackContext({ reason }: { reason: string }) {
  return <section className={styles.fallbackContext} role="status" aria-labelledby="fallback-title">
    <AlertTriangle size={18} aria-hidden="true" />
    <div><h2 id="fallback-title">候选采用 SLA 兜底排程</h2><p>CP-SAT 未提供可用结果。批准前请人工核对阻塞项、步骤变更和延误影响。</p><p><strong>兜底原因：</strong>{fallbackReasonLabel(reason)} <code>{reason}</code></p></div>
  </section>;
}

function BlockerList({ blockers }: { blockers: SchedulePreview["blockers"] }) {
  return <section className={styles.blockerSection} aria-labelledby="blockers-title"><h2 id="blockers-title">阻塞项</h2>{blockers.length ? <ul className={styles.blockerList} aria-label="候选排程阻塞项">{blockers.map((blocker) => <li key={`${blocker.step_id}-${blocker.order_id}`}><strong>{blocker.step_id}</strong><span>{blocker.order_id}</span><p>{blocker.reason}</p></li>)}</ul> : <p className={styles.emptyBlockers}>当前候选未报告阻塞项。</p>}</section>;
}
function AssistanceList({ title, values }: { title: string; values: string[] }) { return <div className={styles.assistanceList}><h3>{title}</h3>{values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p>未提供。</p>}</div>; }

function RejectConfirmation({ pending, onCancel, onConfirm }: { pending: boolean; onCancel: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => { dialogRef.current?.querySelector<HTMLButtonElement>("[data-autofocus]")?.focus(); }, []);
  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") { event.preventDefault(); onCancel(); return; }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])") ?? []);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable.at(-1)!;
    if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  };
  return <div className={styles.modalBackdrop} onMouseDown={(event) => event.stopPropagation()}><section ref={dialogRef} className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="reject-title" aria-describedby="reject-description" onKeyDown={trapFocus}><h2 id="reject-title">拒绝候选排程？</h2><p id="reject-description">拒绝会请求服务端记录该候选排程的处理结果。</p><div><Button variant="secondary" type="button" onClick={onCancel} disabled={pending}>取消</Button><Button data-autofocus variant="danger" type="button" onClick={onConfirm} disabled={pending}>{pending ? "正在确认…" : "确认拒绝"}</Button></div></section></div>;
}

function WorkbenchSkeleton() { return <main className={styles.workbench} aria-busy="true"><section className={styles.skeleton}><span /><span /><span /><span /></section><aside className={styles.skeleton}><span /><span /><span /></aside></main>; }
function LoadError({ label, onRetry }: { label: string; onRetry: () => void }) { return <div className={styles.loadError} role="alert"><XCircle size={18} aria-hidden="true" /><span>无法加载{label}。请检查网络后重试。</span><Button variant="secondary" type="button" onClick={onRetry} aria-label={`重试加载${label}`}><RefreshCw size={16} aria-hidden="true" />重试</Button></div>; }
function EmptyPreview() { return <section className={styles.empty} aria-label="候选排程为空"><Clock3 size={20} aria-hidden="true" />当前没有待审核的候选排程。</section>; }
function Metric({ label, value, note }: { label: string; value: string; note: string }) { return <li><span>{label}</span><strong>{value}</strong><small>{note}</small></li>; }

const formatTime = (value: number) => new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
const formatChangeTime = (value: unknown) => typeof value === "string" ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "未提供";
const reviewOperationKey = (preview: Pick<SchedulePreview, "id" | "version">, action: ReviewAction) => `${preview.id}:${preview.version}:${action}`;
const fallbackReasonLabel = (reason: string) => ({ cp_sat_infeasible: "CP-SAT 判定当前约束无可行解", cp_sat_timeout_without_feasible_solution: "CP-SAT 未在时限内找到可行解", cp_sat_execution_error: "CP-SAT 执行异常", input_size_protection_threshold_exceeded: "输入规模超过求解保护阈值" }[reason] ?? reason);
const previewStatus = (status: SchedulePreview["status"]) => ({ pending_review: "待审核", approved: "已批准", rejected: "已拒绝", conflicted: "冲突", failed: "失败" }[status]);
const previewTone = (status: SchedulePreview["status"]): StatusTone => status === "approved" ? "success" : status === "pending_review" ? "info" : status === "conflicted" || status === "failed" ? "danger" : "neutral";
