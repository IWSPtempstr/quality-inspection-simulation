import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, CheckCircle2, CloudOff, FileWarning, MailOpen, RefreshCw, Send, Sparkles } from "lucide-react";
import { apiRequest, createIdempotencyKey } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { Health, Notification, NotificationDelivery, NotificationDraft, Page } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import styles from "@/features/notifications/NotificationsPage.module.css";

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const session = useSessionStore((state) => state.session);
  const canSend = can(session?.role, "schedule:write");
  const [feedback, setFeedback] = useState("");
  const [failedId, setFailedId] = useState<string | null>(null);
  const [markingId, setMarkingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<NotificationDraft | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const readOperationKeys = useRef<Record<string, string>>({});
  const notifications = useQuery({ queryKey: queryKeys.notifications, queryFn: () => apiRequest<Page<Notification>>("/notifications") });
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<Health>("/system/health") });
  const markRead = useMutation({
    mutationFn: (id: string) => {
      const idempotencyKey = readOperationKeys.current[id] ?? (readOperationKeys.current[id] = createIdempotencyKey());
      return apiRequest<void>(`/notifications/${id}/read`, { method: "PATCH", headers: { "Idempotency-Key": idempotencyKey } });
    },
    onSuccess: (_, id) => { delete readOperationKeys.current[id]; queryClient.setQueryData<Page<Notification>>(queryKeys.notifications, (current) => current ? { ...current, items: current.items.map((item) => item.id === id ? { ...item, status: "read" } : item) } : current); setMarkingId(null); setFailedId(null); setFeedback("服务端已确认通知已读"); },
    onError: (error, id) => { setMarkingId(null); setFailedId(id); setFeedback(error instanceof ApiProblem && error.isConflict ? "通知状态已发生冲突，通知仍保持原状态。" : "服务端未确认通知已读，请检查网络后重试。"); },
  });
  const createDraft = useMutation({ mutationFn: (notificationId: string) => apiRequest<NotificationDraft>("/notification-drafts", { method: "POST", body: JSON.stringify({ notification_id: notificationId }) }), onSuccess: (result) => { setDraft(result); setDraftBody(result.body); } });
  const sendDraft = useMutation({ mutationFn: (current: NotificationDraft) => apiRequest<NotificationDelivery>(`/notification-drafts/${current.draft_id}/send`, { method: "POST", headers: { "Idempotency-Key": createIdempotencyKey() }, body: JSON.stringify({ source_hash: current.source_hash, body: draftBody }) }), onSuccess: () => { setFeedback("通知已由服务端接受发送，实际投递由确定性通知服务处理。"); setDraft(null); setDraftBody(""); }, onError: () => setFeedback("服务端未接受通知发送，请检查后重试。") });
  return <>
    <PageHeader title="通知" description="通知状态以服务端确认结果为准。" />
    {health.data?.status === "degraded" ? <p className={styles.degraded}><FileWarning size={18} aria-hidden="true" />部分服务降级，通知记录仍可单独读取。</p> : null}
    {health.isError ? <p className={styles.degraded}><CloudOff size={18} aria-hidden="true" />服务健康状态暂不可用。</p> : null}
    {feedback ? <p className={failedId ? styles.failure : styles.feedback} role={failedId ? "alert" : "status"}>{failedId ? null : <CheckCircle2 size={18} aria-hidden="true" />}{feedback}</p> : null}
    <section className={styles.surface} aria-labelledby="notifications-title"><div className={styles.heading}><div><h2 id="notifications-title">收件箱</h2><p>仅展示服务端已记录的通知。</p></div><span>{notifications.data?.total ?? "-"} 项</span></div>{canSend && notifications.data?.items[0] ? <div className={styles.draftPanel}><div><h3>通知内容增强</h3><p>规则已确定收件人、触发条件和渠道；助手仅提供正文草稿。</p></div><Button variant="secondary" type="button" onClick={() => createDraft.mutate(notifications.data.items[0].id)} disabled={createDraft.isPending}><Sparkles size={16} aria-hidden="true" />{createDraft.isPending ? "正在生成草稿" : "生成通知草稿"}</Button>{draft ? <div className={styles.draftEditor}><label>通知正文<textarea value={draftBody} onChange={(event) => setDraftBody(event.target.value)} aria-label="编辑通知正文" rows={4} /></label><small>可编辑草稿不会自动发送。</small><Button type="button" onClick={() => sendDraft.mutate(draft)} disabled={sendDraft.isPending || !draftBody.trim()}><Send size={16} aria-hidden="true" />{sendDraft.isPending ? "正在提交发送" : "确认发送"}</Button></div> : null}</div> : null}
      {notifications.isLoading ? <div className={styles.state} aria-busy="true">正在加载通知…</div> : notifications.isError ? <div className={styles.state} role="alert">无法加载通知。请检查网络后重试。<Button variant="secondary" type="button" onClick={() => notifications.refetch()} aria-label="重试加载通知"><RefreshCw size={16} aria-hidden="true" />重试</Button></div> : !notifications.data?.items.length ? <div className={styles.state}><BellOff size={20} aria-hidden="true" />当前没有通知。</div> : <ul className={styles.list}>{notifications.data.items.map((item) => <NotificationItem key={item.id} item={item} pending={markingId === item.id} failed={failedId === item.id} onRead={() => { setMarkingId(item.id); markRead.mutate(item.id); }} />)}</ul>}
    </section>
  </>;
}

function NotificationItem({ item, pending, failed, onRead }: { item: Notification; pending: boolean; failed: boolean; onRead: () => void }) {
  const unread = item.status === "unread";
  return <li className={unread ? styles.unread : ""} aria-label={`${item.title} ${unread ? "未读" : "已读"}`}><div><strong>{item.title}</strong><span>{formatDate(item.created_at)} · {unread ? "未读" : "已读"}</span></div>{unread ? <Button variant="secondary" type="button" onClick={onRead} disabled={pending} aria-label={failed ? `重试标记已读 ${item.id}` : `标记为已读 ${item.id}`}>{pending ? "等待服务端确认" : failed ? "重试标记已读" : <><MailOpen size={16} aria-hidden="true" />标记为已读</>}</Button> : <span className={styles.confirmed}><CheckCircle2 size={16} aria-hidden="true" />已确认</span>}</li>;
}

const formatDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
