import { useEffect, useRef, useState, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BookOpenCheck, CheckCircle2, CircleOff, CloudOff, FileCheck2, FileWarning, RefreshCw, ShieldCheck, X } from "lucide-react";
import { apiRequest, createIdempotencyKey } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { Diagnosis, Event, ExceptionCaseCandidate, ExceptionCaseReview, Page } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";
import styles from "@/features/events/EventsPage.module.css";

type DiagnosisRequest = { eventId: string; idempotencyKey: string };
type CloseRequest = { event: Event; idempotencyKey: string };

export function EventsPage() {
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const canClose = can(session?.role, "events:write");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [diagnosisOpen, setDiagnosisOpen] = useState(false);
  const [caseCandidate, setCaseCandidate] = useState<ExceptionCaseCandidate | null>(null);
  const [caseNotice, setCaseNotice] = useState("");
  const [feedback, setFeedback] = useState("");
  const [conflict, setConflict] = useState(false);
  const [closeRequested, setCloseRequested] = useState(false);
  const [diagnosisRetry, setDiagnosisRetry] = useState<DiagnosisRequest | null>(null);
  const [closeRetry, setCloseRetry] = useState<CloseRequest | null>(null);
  const closeTriggerRef = useRef<HTMLButtonElement>(null);
  const events = useQuery({ queryKey: queryKeys.events, queryFn: () => apiRequest<Page<Event>>("/events") });
  const detail = useQuery({ queryKey: ["events", selectedId], queryFn: () => apiRequest<Event>(`/events/${selectedId}`), enabled: Boolean(selectedId) });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<{ status: "healthy" | "degraded" }>("/system/health") });
  const selected = detail.data ?? events.data?.items.find((event) => event.id === selectedId) ?? null;

  const diagnose = useMutation({
    mutationFn: ({ eventId, idempotencyKey }: DiagnosisRequest) => apiRequest<Diagnosis>(`/events/${eventId}/diagnose`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } }),
    onSuccess: (result) => { setDiagnosis(result); setDiagnosisRetry(null); setFeedback("诊断已由服务端返回，以下内容仅供人工判断。 "); },
    onError: (_error, variables) => { setDiagnosisRetry(variables); setFeedback("无法获取诊断。事件状态未改变，请检查网络后重试。"); },
  });
  const createCaseCandidate = useMutation({
    mutationFn: (eventId: string) => apiRequest<ExceptionCaseCandidate>(`/events/${eventId}/case-candidates`, { method: "POST" }),
    onSuccess: (result) => { setCaseCandidate(result); setCaseNotice(""); },
    onError: () => setCaseNotice("无法生成案例候选。事件和正式记忆均未发生变化。"),
  });
  const submitCaseCandidate = useMutation({
    mutationFn: (candidate: ExceptionCaseCandidate) => apiRequest<ExceptionCaseReview>(`/exception-case-candidates/${candidate.candidate_id}/submit`, { method: "POST", headers: { "If-Match": selected ? String(selected.version) : "0", "Idempotency-Key": createIdempotencyKey() }, body: JSON.stringify({ source_candidate_hash: candidate.source_candidate_hash, summary: candidate.summary, trigger: candidate.trigger, impact: candidate.impact, disposition: candidate.disposition, outcome: candidate.outcome, tags: candidate.tags, retention_until: candidate.retention_until }) }),
    onSuccess: () => { setCaseNotice("案例已提交至审核队列，尚未进入长期记忆或检索结果。"); setCaseCandidate(null); },
    onError: () => setCaseNotice("案例候选未能提交审核，长期记忆未发生变化。"),
  });
  const close = useMutation({
    mutationFn: ({ event, idempotencyKey }: CloseRequest) => apiRequest<Event>(`/events/${event.id}/close`, { method: "POST", headers: { "If-Match": String(event.version), "Idempotency-Key": idempotencyKey } }),
    onSuccess: (result) => {
      queryClient.setQueryData<Page<Event>>(queryKeys.events, (current) => current ? { ...current, items: current.items.map((event) => event.id === result.id ? result : event) } : current);
      queryClient.setQueryData(["events", result.id], result);
      setCloseRequested(false);
      setCloseRetry(null);
      setConflict(false);
      setFeedback("事件已由服务端确认关闭。请继续保留现场处置记录。 ");
    },
    onError: async (error, variables) => {
      setCloseRequested(false);
      if (error instanceof ApiProblem && error.isConflict) { setCloseRetry(null); setConflict(true); await queryClient.invalidateQueries({ queryKey: queryKeys.events }); await detail.refetch(); return; }
      setCloseRetry(variables);
      setFeedback(error instanceof ApiProblem && error.isDegraded ? "事件关闭服务暂时降级。事件仍保持原状态，请稍后重试。" : "服务端未确认关闭事件，当前状态未变。请检查网络后重试。");
    },
  });

  const select = (id: string) => { setSelectedId(id); setDiagnosis(null); setDiagnosisOpen(false); setCaseCandidate(null); setCaseNotice(""); setFeedback(""); setConflict(false); setDiagnosisRetry(null); setCloseRetry(null); };
  const refresh = async () => { setConflict(false); setFeedback(""); await Promise.all([events.refetch(), selectedId ? detail.refetch() : Promise.resolve()]); };

  return <>
    <PageHeader title="事件处置" description="诊断为带证据的只读辅助信息；关闭事件必须由人工确认并等待服务端结果。" />
    {health.data?.status === "degraded" ? <p className={styles.degraded} role="status"><FileWarning size={18} aria-hidden="true" />辅助诊断服务降级中。事件事实仍可读取；请将诊断结论视为待核实信息。</p> : null}
    {health.isError ? <p className={styles.degraded} role="status"><CloudOff size={18} aria-hidden="true" />服务健康状态暂不可用。请以事件详情中的版本和证据为准。</p> : null}
    {feedback ? <div className={styles.feedback} role="status"><CheckCircle2 size={18} aria-hidden="true" /><span>{feedback}</span>{diagnosisRetry ? <Button variant="secondary" type="button" onClick={() => diagnose.mutate(diagnosisRetry)} aria-label="重试获取诊断"><RefreshCw size={16} aria-hidden="true" />重试诊断</Button> : closeRetry ? <Button variant="secondary" type="button" onClick={() => close.mutate(closeRetry)} aria-label="重试关闭事件"><RefreshCw size={16} aria-hidden="true" />重试关闭</Button> : null}</div> : null}
    {conflict ? <div className={styles.conflict} role="alert"><AlertTriangle size={19} aria-hidden="true" /><div><strong>事件已发生版本冲突</strong><p>其他调度员或服务端已更新事件。已请求最新信息，请核对后再关闭。</p></div><Button variant="secondary" type="button" onClick={() => void refresh()} aria-label="刷新事件信息"><RefreshCw size={16} aria-hidden="true" />刷新</Button></div> : null}
    <main className={styles.layout}>
      <EventList events={events} selectedId={selectedId} onSelect={select} />
      <EventDetail event={selected} loading={detail.isLoading} loadError={detail.isError} diagnosisPending={diagnose.isPending} candidatePending={createCaseCandidate.isPending} closePending={close.isPending} canClose={canClose} onDiagnose={() => { if (!selected) return; setDiagnosisOpen(true); diagnose.mutate({ eventId: selected.id, idempotencyKey: createIdempotencyKey() }); }} onCaseCandidate={() => selected && createCaseCandidate.mutate(selected.id)} onClose={(trigger) => { closeTriggerRef.current = trigger; setCloseRequested(true); }} onRetry={() => selectedId ? detail.refetch() : events.refetch()} />
    </main>
    {closeRequested && selected ? <CloseDialog event={selected} pending={close.isPending} returnFocusRef={closeTriggerRef} onCancel={() => setCloseRequested(false)} onConfirm={() => close.mutate({ event: selected, idempotencyKey: createIdempotencyKey() })} /> : null}
    {diagnosisOpen && selected ? <DiagnosisDrawer event={selected} diagnosis={diagnosis} pending={diagnose.isPending} onClose={() => setDiagnosisOpen(false)} /> : null}
    {caseCandidate ? <CaseCandidateDrawer candidate={caseCandidate} pending={submitCaseCandidate.isPending} onClose={() => setCaseCandidate(null)} onSubmit={(candidate) => submitCaseCandidate.mutate(candidate)} /> : null}
    {caseNotice ? <p className={styles.feedback} role={caseNotice.includes("未能") || caseNotice.includes("无法") ? "alert" : "status"}>{caseNotice}</p> : null}
  </>;
}

function EventList({ events, selectedId, onSelect }: { events: ReturnType<typeof useQuery<Page<Event>>>; selectedId: string | null; onSelect: (id: string) => void }) {
  return <section className={styles.listSurface} aria-labelledby="event-list-title"><div className={styles.sectionHeader}><div><h2 id="event-list-title">事件列表</h2><p>选择事件查看事实、影响和证据。</p></div><span>{events.data?.total ?? "-"} 项</span></div>{events.isLoading ? <div className={styles.skeleton} aria-busy="true"><span /><span /></div> : events.isError ? <div className={styles.loadError} role="alert">无法加载事件列表。请检查网络后重试。<Button variant="secondary" type="button" onClick={() => events.refetch()} aria-label="重试加载事件列表">重试</Button></div> : !events.data?.items.length ? <div className={styles.empty}><CircleOff size={20} aria-hidden="true" />当前没有事件。</div> : <ul className={styles.eventList}>{events.data.items.map((event) => <li key={event.id}><button type="button" className={event.id === selectedId ? styles.selected : ""} onClick={() => onSelect(event.id)} aria-label={`查看 ${event.id}`}><span><strong>{event.event_type}</strong><small>{event.id} · {event.entity_id ?? "未关联对象"}</small></span><StatusBadge tone={severityTone(event.severity)}>{severityLabel(event.severity)}</StatusBadge><small>{eventLabel(event.status)}</small></button></li>)}</ul>}</section>;
}

function EventDetail({ event, loading, loadError, diagnosisPending, candidatePending, closePending, canClose, onDiagnose, onCaseCandidate, onClose, onRetry }: { event: Event | null; loading: boolean; loadError: boolean; diagnosisPending: boolean; candidatePending: boolean; closePending: boolean; canClose: boolean; onDiagnose: () => void; onCaseCandidate: () => void; onClose: (trigger: HTMLButtonElement) => void; onRetry: () => void }) {
  if (!event && !loading) return <section className={styles.detailSurface} aria-label="事件详情"><div className={styles.empty}><ShieldCheck size={22} aria-hidden="true" />从列表选择一个事件以查看处理信息。</div></section>;
  if (loading) return <section className={styles.detailSurface} aria-busy="true"><div className={styles.skeleton}><span /><span /><span /></div></section>;
  if (loadError || !event) return <section className={styles.detailSurface}><div className={styles.loadError} role="alert">无法加载事件详情。<Button variant="secondary" type="button" onClick={onRetry} aria-label="重试加载事件详情">重试</Button></div></section>;
  return <section className={styles.detailSurface} aria-labelledby="event-detail-title"><div className={styles.detailHeader}><div><p>事件详情</p><h2 id="event-detail-title">{event.event_type}</h2><span>{event.id} · 版本 v{event.version}</span></div><StatusBadge tone={severityTone(event.severity)}>{severityLabel(event.severity)}</StatusBadge></div><dl className={styles.facts}><div><dt>关联对象</dt><dd>{event.entity_id ?? "未关联"}</dd></div><div><dt>发生时间</dt><dd>{formatDate(event.occurred_at)}</dd></div><div><dt>当前状态</dt><dd>{eventLabel(event.status)}</dd></div></dl><section className={styles.payload} aria-labelledby="fact-title"><h3 id="fact-title">已报告事实</h3>{Object.keys(event.payload).length ? <dl>{Object.entries(event.payload).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl> : <p>事件未附加更多事实字段。</p>}</section><div className={styles.detailActions}><Button variant="secondary" type="button" onClick={onDiagnose} disabled={diagnosisPending}>{diagnosisPending ? "正在读取服务端诊断" : <><BookOpenCheck size={16} aria-hidden="true" />获取诊断</>}</Button>{canClose && event.status === "closed" ? <Button variant="secondary" type="button" onClick={onCaseCandidate} disabled={candidatePending}>{candidatePending ? "正在生成候选" : <><FileCheck2 size={16} aria-hidden="true" />异常案例候选</>}</Button> : null}{canClose && event.status !== "closed" ? <Button variant="danger" type="button" onClick={(clickEvent) => onClose(clickEvent.currentTarget)} disabled={closePending} aria-label="人工关闭事件">人工关闭</Button> : <span className={styles.readOnly}>{canClose ? "事件已关闭，可人工整理案例候选" : "当前角色仅可查看事件"}</span>}</div></section>;
}

function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis }) { const frozenSteps = diagnosis.frozen_step_ids ?? []; const affectedResources = diagnosis.affected_resources ?? []; return <section className={styles.diagnosis} aria-labelledby="diagnosis-title"><div className={styles.diagnosisHeader}><div><h3 id="diagnosis-title">诊断结果</h3><p>诊断仅供人工判断，不会执行排程或变更资源。</p></div><StatusBadge tone={confidenceTone(diagnosis.confidence)}>{confidenceLabel(diagnosis.confidence)}</StatusBadge></div><DiagnosisList title="影响订单" values={diagnosis.affected_order_ids} empty="未识别到受影响订单。" /><DiagnosisList title="冻结步骤" values={frozenSteps} empty="未识别到冻结步骤。" /><DiagnosisList title="受影响资源" values={affectedResources.map((resource) => `${String(resource.resource_id ?? "资源")}：${String(resource.impact ?? "待评估")}`)} empty="未识别到受影响资源。" /><DiagnosisList title="SLA 风险" values={diagnosis.sla_risks.map((risk) => `${String(risk.order_id ?? "订单")}：${String(risk.risk ?? "待评估")}`)} empty="未报告 SLA 风险。" /><DiagnosisList title="人工建议" values={diagnosis.recommendations} empty="未提供建议。" /><DiagnosisList title="证据缺口" values={diagnosis.evidence_gaps} empty="当前诊断未报告证据缺口。" /><section className={styles.evidence} aria-labelledby="evidence-title"><h4 id="evidence-title">引用证据</h4>{diagnosis.evidence.length ? <ul>{diagnosis.evidence.map((citation) => <li key={`${citation.standard_title}-${citation.clause}-${citation.page}`}><strong>{citation.standard_title}</strong><span>{citation.version} · {citation.clause} · 第 {citation.page} 页</span><p>{citation.content}</p><a href={`/knowledge?standard=${encodeURIComponent(citation.standard_title)}&clause=${encodeURIComponent(citation.clause)}`}>在知识库查看证据</a></li>)}</ul> : <p>未提供可引用证据，不能据此作出自动处置。</p>}</section></section>; }
function DiagnosisDrawer({ event, diagnosis, pending, onClose }: { event: Event; diagnosis: Diagnosis | null; pending: boolean; onClose: () => void }) { return <div className={styles.drawerBackdrop}><aside className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby="diagnosis-drawer-title"><div className={styles.drawerHeader}><div><p>智能诊断助手 · {event.id}</p><h2 id="diagnosis-drawer-title">异常诊断</h2></div><Button variant="ghost" type="button" onClick={onClose} aria-label="关闭异常诊断"><X size={18} aria-hidden="true" /></Button></div>{pending ? <div className={styles.skeleton} aria-busy="true"><span /><span /><span /></div> : diagnosis ? <DiagnosisPanel diagnosis={diagnosis} /> : <div className={styles.empty}>当前没有诊断结果，请关闭后重试。</div>}</aside></div>; }
function CaseCandidateDrawer({ candidate, pending, onClose, onSubmit }: { candidate: ExceptionCaseCandidate; pending: boolean; onClose: () => void; onSubmit: (candidate: ExceptionCaseCandidate) => void }) { const [draft, setDraft] = useState(candidate); return <div className={styles.drawerBackdrop}><aside className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby="case-candidate-title"><div className={styles.drawerHeader}><div><p>仅候选，尚未进入长期记忆</p><h2 id="case-candidate-title">异常案例候选</h2></div><Button variant="ghost" type="button" onClick={onClose} disabled={pending} aria-label="关闭案例候选"><X size={18} aria-hidden="true" /></Button></div><div className={styles.candidate}><label>摘要<textarea value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} /></label><p><strong>触发：</strong>{draft.trigger}</p><label>影响<textarea value={draft.impact} onChange={(event) => setDraft({ ...draft, impact: event.target.value })} /></label><label>处置<textarea value={draft.disposition} onChange={(event) => setDraft({ ...draft, disposition: event.target.value })} /></label><label>结果<textarea value={draft.outcome} onChange={(event) => setDraft({ ...draft, outcome: event.target.value })} /></label><label>标签<input value={draft.tags.join(", ")} onChange={(event) => setDraft({ ...draft, tags: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) })} /></label><p><strong>保留至：</strong>{formatDate(draft.retention_until)}</p></div><div className={styles.drawerActions}><Button variant="secondary" type="button" onClick={onClose} disabled={pending}>取消</Button><Button type="button" onClick={() => onSubmit(draft)} disabled={pending || !draft.summary.trim() || !draft.impact.trim() || !draft.disposition.trim() || !draft.outcome.trim()}>{pending ? "正在提交审核" : "提交审核"}</Button></div></aside></div>; }
function DiagnosisList({ title, values, empty }: { title: string; values: string[]; empty: string }) { return <section className={styles.diagnosisList}><h4>{title}</h4>{values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p>{empty}</p>}</section>; }

function CloseDialog({ event, pending, returnFocusRef, onCancel, onConfirm }: { event: Event; pending: boolean; returnFocusRef: RefObject<HTMLButtonElement | null>; onCancel: () => void; onConfirm: () => void }) {
  const ref = useRef<HTMLElement>(null);
  const pendingRef = useRef(pending);
  const cancelRef = useRef(onCancel);
  pendingRef.current = pending;
  cancelRef.current = onCancel;

  useEffect(() => {
    const dialog = ref.current;
    const trigger = returnFocusRef.current;
    if (!dialog) return;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])"));
    const initialFocus = dialog.querySelector<HTMLButtonElement>("[data-autofocus]");
    initialFocus?.focus();
    const onKeyDown = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === "Escape" && !pendingRef.current) { keyboardEvent.preventDefault(); cancelRef.current(); return; }
      if (keyboardEvent.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) { keyboardEvent.preventDefault(); return; }
      const first = controls[0];
      const last = controls[controls.length - 1];
      const active = document.activeElement;
      if (keyboardEvent.shiftKey && (active === first || !dialog.contains(active))) { keyboardEvent.preventDefault(); last.focus(); }
      else if (!keyboardEvent.shiftKey && (active === last || !dialog.contains(active))) { keyboardEvent.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); trigger?.focus(); };
  }, [returnFocusRef]);

  return <div className={styles.backdrop}><section ref={ref} className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="close-title" aria-describedby="close-description"><div><h2 id="close-title">关闭事件 {event.id}</h2><button type="button" onClick={onCancel} disabled={pending} aria-label="取消关闭"><X size={18} aria-hidden="true" /></button></div><p id="close-description">此操作将请求服务端按事件版本 v{event.version} 记录人工关闭。不会自动改动排程、订单或资源。</p><footer><Button variant="secondary" type="button" onClick={onCancel} disabled={pending}>取消</Button><Button data-autofocus variant="danger" type="button" onClick={onConfirm} disabled={pending}>{pending ? "正在等待服务端确认" : "确认关闭事件"}</Button></footer></section></div>;
}

const eventLabel = (status: string) => ({ open: "待处理", closed: "已关闭", investigating: "处理中" }[status] ?? status);
const severityLabel = (severity: string) => ({ high: "高风险", medium: "中风险", low: "低风险" }[severity] ?? severity);
const severityTone = (severity: string): StatusTone => severity === "high" ? "danger" : severity === "medium" ? "warning" : "info";
const confidenceLabel = (value: Diagnosis["confidence"]) => ({ high: "证据充分", medium: "需复核", low: "证据有限", insufficient: "证据不足" }[value]);
const confidenceTone = (value: Diagnosis["confidence"]): StatusTone => value === "high" ? "success" : value === "medium" ? "info" : "warning";
const formatDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
