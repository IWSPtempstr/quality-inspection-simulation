import { useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useForm } from "react-hook-form";
import { FilePenLine, FileSearch, Filter, FlaskConical, Plus, RotateCcw, X } from "lucide-react";
import { apiRequest, createIdempotencyKey, type IdempotencyKey } from "@/api/client";
import { ApiProblem } from "@/api/problem";
import { queryKeys } from "@/api/queryKeys";
import type { DataQualityPreflight, Order, OrderInput, Page } from "@/api/types";
import { can } from "@/auth/permissions";
import { useSessionStore } from "@/auth/sessionStore";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";
import { orderPatchSchema, orderSchema, retestSchema, type OrderFormValues, type OrderPatchFormValues, type RetestFormValues } from "@/features/orders/orderSchema";
import styles from "@/features/orders/OrdersPage.module.css";

const projects = [["safety", "安全"], ["emc", "电磁兼容"], ["environment", "环境可靠性"]] as const;
const emptyOrder: OrderFormValues = { priority: "normal", sample_quantity: 1, certification_type: "CCC", project_ids: [], sample_name: "", promised_finish_time: "" };
type IdempotentOperation<T> = { values: T; idempotencyKey: IdempotencyKey };

export function OrdersPage() {
  const session = useSessionStore((state) => state.session);
  const canWrite = can(session?.role, "orders:write");
  const [query, setQuery] = useState("");
  const [editingOrder, setEditingOrder] = useState<Order | null>(null);
  const [retestingOrder, setRetestingOrder] = useState<Order | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const orders = useQuery({ queryKey: queryKeys.orders(query), queryFn: () => apiRequest<Page<Order>>(`/orders${query ? `?q=${encodeURIComponent(query)}` : ""}`) });
  return <><PageHeader title="订单" description="录入已确认的样品信息与检测项目。系统不会生成订单草稿或推荐检测项目。" />{notice ? <p className={styles.success} role="status">{notice}</p> : null}<section className={styles.layout}>{canWrite ? <OrderForm /> : null}<section className={styles.listSurface} aria-labelledby="order-list-title"><div className={styles.listHeader}><div><h2 id="order-list-title">订单列表</h2><p>按订单号、样品名称或状态筛选。</p></div><label className={styles.search}><Filter size={16} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索订单或样品" aria-label="搜索订单或样品" /></label></div>{orders.isLoading ? <TableSkeleton /> : orders.isError ? <section className={styles.tableState}><span>无法加载订单。请检查网络后重试。</span><Button variant="secondary" type="button" onClick={() => orders.refetch()}>重试</Button></section> : <OrderTable orders={orders.data?.items ?? []} canWrite={canWrite} onEdit={setEditingOrder} onRetest={setRetestingOrder} />}</section></section>{editingOrder ? <OrderEditDialog order={editingOrder} onLatest={setEditingOrder} onClose={() => setEditingOrder(null)} /> : null}{retestingOrder ? <RetestDialog order={retestingOrder} onSuccess={() => setNotice("复测订单已创建，等待服务端排程。")} onClose={() => setRetestingOrder(null)} /> : null}</>;
}

function OrderForm() {
  const queryClient = useQueryClient();
  const form = useForm<OrderFormValues>({ resolver: zodResolver(orderSchema), defaultValues: emptyOrder });
  const operationKey = useOperationKey();
  const create = useMutation({ mutationFn: ({ values, idempotencyKey }: IdempotentOperation<OrderInput>) => apiRequest<Order>("/orders", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ ...values, promised_finish_time: toApiTimestamp(values.promised_finish_time) }) }), onSuccess: (_, operation) => { operationKey.release(operation.idempotencyKey); queryClient.invalidateQueries({ queryKey: ["orders"] }); form.reset(emptyOrder); } });
  const [preflight, setPreflight] = useState<DataQualityPreflight | null>(null);
  const check = useMutation({ mutationFn: () => apiRequest<DataQualityPreflight>("/schedule-previews/preflight", { method: "POST", body: JSON.stringify({ scope: "order" }) }), onSuccess: setPreflight });
  const selected = form.watch("project_ids");
  return <section className={styles.formSurface} aria-labelledby="create-order-title"><div><h2 id="create-order-title">创建订单</h2><p>检测项目由职工按确认结果选择。</p></div><form onSubmit={form.handleSubmit((values) => create.mutate({ values, idempotencyKey: operationKey.acquire(values) }))} noValidate><Field label="样品名称" error={form.formState.errors.sample_name?.message}><input {...form.register("sample_name")} /></Field><div className={styles.twoCols}><Field label="样品数量" error={form.formState.errors.sample_quantity?.message}><input type="number" min="1" {...form.register("sample_quantity")} /></Field><Field label="订单优先级" error={form.formState.errors.priority?.message}><PrioritySelect registration={form.register("priority")} /></Field></div><Field label="认证类型" error={form.formState.errors.certification_type?.message}><select {...form.register("certification_type")}><option value="CCC">CCC</option><option value="CVC">CVC</option><option value="国际认证">国际认证</option></select></Field><Field label="承诺完成时间" error={form.formState.errors.promised_finish_time?.message}><input type="datetime-local" {...form.register("promised_finish_time")} /></Field><ProjectFields selected={selected} onChange={(ids) => form.setValue("project_ids", ids, { shouldValidate: true })} error={form.formState.errors.project_ids?.message} /><Button variant="secondary" type="button" onClick={() => check.mutate()} disabled={check.isPending}><FileSearch size={16} aria-hidden="true" />{check.isPending ? "正在检查" : "数据质量预检"}</Button>{preflight ? <section className={styles.preflight} aria-labelledby="order-preflight-title"><h3 id="order-preflight-title">订单预检</h3><p>{preflight.status === "blocked" ? "存在阻塞规则，不能由助手自动修正。" : "未发现阻塞规则。"}</p>{preflight.findings.map((finding) => <p key={finding.code}><strong>{finding.blocking ? "阻塞：" : "提示："}</strong>{finding.message}{finding.suggestion ? ` ${finding.suggestion}` : ""}</p>)}</section> : null}{problemMessage(create.error, "创建订单失败，请重试。") ? <p className={styles.error} role="alert">{problemMessage(create.error, "创建订单失败，请重试。")}</p> : null}{create.isSuccess ? <p className={styles.success} role="status">订单已创建，等待服务端排程。</p> : null}<Button type="submit" disabled={create.isPending}><Plus size={16} aria-hidden="true" />{create.isPending ? "正在创建" : "创建订单"}</Button></form></section>;
}

function OrderEditDialog({ order, onLatest, onClose }: { order: Order; onLatest: (order: Order) => void; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<OrderPatchFormValues>({ resolver: zodResolver(orderPatchSchema), defaultValues: editableValues(order) });
  const operationKey = useOperationKey();
  const reload = useMutation({ mutationFn: () => apiRequest<Order>(`/orders/${order.id}`), onSuccess: (latest) => { form.reset(editableValues(latest)); onLatest(latest); } });
  const update = useMutation({ mutationFn: ({ values, idempotencyKey }: IdempotentOperation<OrderPatchFormValues>) => apiRequest<Order>(`/orders/${order.id}`, { method: "PATCH", headers: { "If-Match": String(order.version), "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ ...values, promised_finish_time: toApiTimestamp(values.promised_finish_time) }) }), onSuccess: (_, operation) => { operationKey.release(operation.idempotencyKey); queryClient.invalidateQueries({ queryKey: ["orders"] }); onClose(); } });
  const error = problemMessage(update.error, "保存订单失败，请重试。");
  const selected = form.watch("project_ids");
  const isConflict = update.error instanceof ApiProblem && update.error.isConflict;
  return <Dialog title="编辑订单" detail={`${order.id}，版本 v${order.version}`} closeLabel="关闭编辑订单" onClose={onClose}><form onSubmit={form.handleSubmit((values) => update.mutate({ values, idempotencyKey: operationKey.acquire(values) }))} noValidate><Field label="订单优先级" error={form.formState.errors.priority?.message}><PrioritySelect registration={form.register("priority")} /></Field><Field label="承诺完成时间" error={form.formState.errors.promised_finish_time?.message}><input type="datetime-local" {...form.register("promised_finish_time")} /></Field><ProjectFields selected={selected} onChange={(ids) => form.setValue("project_ids", ids, { shouldValidate: true })} error={form.formState.errors.project_ids?.message} />{error ? <div className={styles.error} role="alert"><p>{error}{isConflict ? "。订单版本已过期，请重新加载服务器版本后再保存。" : ""}</p>{isConflict ? <Button variant="secondary" type="button" onClick={() => reload.mutate()} disabled={reload.isPending}>{reload.isPending ? "正在加载" : "重新加载服务器版本"}</Button> : null}{reload.error ? <p>{problemMessage(reload.error, "无法加载服务器最新版本，请重试。")}</p> : null}</div> : null}<DialogActions pending={update.isPending} label="保存修改" onClose={onClose} /></form></Dialog>;
}

function RetestDialog({ order, onSuccess, onClose }: { order: Order; onSuccess: () => void; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<RetestFormValues>({ resolver: zodResolver(retestSchema), defaultValues: { reason: "" } });
  const operationKey = useOperationKey();
  const retest = useMutation({ mutationFn: ({ values, idempotencyKey }: IdempotentOperation<RetestFormValues>) => apiRequest<Order>(`/orders/${order.id}/retests`, { method: "POST", headers: { "If-Match": String(order.version), "Idempotency-Key": idempotencyKey }, body: JSON.stringify(values) }), onSuccess: (_, operation) => { operationKey.release(operation.idempotencyKey); queryClient.invalidateQueries({ queryKey: ["orders"] }); onSuccess(); onClose(); } });
  const isConflict = retest.error instanceof ApiProblem && retest.error.isConflict;
  return <Dialog title="发起复测" detail={`${order.id} 将创建新的待排程复测订单。`} closeLabel="关闭发起复测" onClose={onClose}><form onSubmit={form.handleSubmit((values) => retest.mutate({ values, idempotencyKey: operationKey.acquire(values) }))} noValidate><Field label="复测原因" error={form.formState.errors.reason?.message}><textarea rows={4} {...form.register("reason")} /></Field>{problemMessage(retest.error, "发起复测失败，请重试。") ? <p className={styles.error} role="alert">{problemMessage(retest.error, "发起复测失败，请重试。")} {isConflict ? "订单版本已过期，请关闭后刷新列表再重试。" : ""}</p> : null}<DialogActions pending={retest.isPending} label="确认发起复测" onClose={onClose} /></form></Dialog>;
}

function Dialog({ title, detail, closeLabel, onClose, children }: { title: string; detail: string; closeLabel: string; onClose: () => void; children: React.ReactNode }) { return <DialogPrimitive.Root open onOpenChange={(open) => { if (!open) onClose(); }}><DialogPrimitive.Portal><DialogPrimitive.Overlay className={styles.dialogBackdrop} /><DialogPrimitive.Content className={styles.dialog}><div className={styles.dialogHeader}><div><DialogPrimitive.Title>{title}</DialogPrimitive.Title><DialogPrimitive.Description>{detail}</DialogPrimitive.Description></div><DialogPrimitive.Close asChild><Button variant="ghost" type="button" aria-label={closeLabel}><X size={18} aria-hidden="true" /></Button></DialogPrimitive.Close></div>{children}</DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>; }
function useOperationKey() {
  const active = useRef<{ fingerprint: string; key: IdempotencyKey } | null>(null);
  return {
    acquire(values: unknown) {
      const fingerprint = JSON.stringify(values);
      if (!active.current || active.current.fingerprint !== fingerprint) active.current = { fingerprint, key: createIdempotencyKey() };
      return active.current.key;
    },
    release(key: IdempotencyKey) {
      if (active.current?.key === key) active.current = null;
    },
  };
}
function DialogActions({ pending, label, onClose }: { pending: boolean; label: string; onClose: () => void }) { return <div className={styles.dialogActions}><Button variant="secondary" type="button" onClick={onClose}>取消</Button><Button type="submit" disabled={pending}>{pending ? "正在提交" : label}</Button></div>; }
function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) { return <label className={styles.field}><span>{label}</span>{children}{error ? <small className={styles.error}>{error}</small> : null}</label>; }
function PrioritySelect({ registration }: { registration: React.SelectHTMLAttributes<HTMLSelectElement> }) { return <select {...registration}><option value="normal">普通</option><option value="urgent">加急</option><option value="vip">VIP</option></select>; }
function ProjectFields({ selected, onChange, error }: { selected: string[]; onChange: (ids: string[]) => void; error?: string }) { return <fieldset className={styles.projects}><legend>检测项目</legend>{projects.map(([id, label]) => <label key={id}><input type="checkbox" checked={selected.includes(id)} onChange={(event) => onChange(event.target.checked ? [...selected, id] : selected.filter((item) => item !== id))} />{label}</label>)}{error ? <span className={styles.error}>{error}</span> : null}</fieldset>; }
function OrderTable({ orders, canWrite, onEdit, onRetest }: { orders: Order[]; canWrite: boolean; onEdit: (order: Order) => void; onRetest: (order: Order) => void }) { if (!orders.length) return <section className={styles.tableState}>没有符合筛选条件的订单。</section>; return <div className={styles.tableWrap}><table><thead><tr><th>订单号</th><th>样品</th><th>认证</th><th>优先级</th><th>检测项目</th><th>状态</th><th>承诺完成</th>{canWrite ? <th>操作</th> : null}</tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td>{order.id}</td><td><strong>{order.sample_name}</strong><small>{order.sample_quantity} 件</small></td><td>{order.certification_type}</td><td><StatusBadge tone={priorityTone(order.priority)}>{priorityLabel(order.priority)}</StatusBadge></td><td>{order.project_ids.join(" / ")}</td><td><StatusBadge tone={statusTone(order.status)}>{statusLabel(order.status)}</StatusBadge></td><td>{formatDate(order.promised_finish_time)}</td>{canWrite ? <td><div className={styles.rowActions}><Button variant="ghost" type="button" aria-label={`编辑 ${order.id}`} onClick={() => onEdit(order)}><FilePenLine size={16} aria-hidden="true" />编辑</Button><Button variant="ghost" type="button" aria-label={`复测 ${order.id}`} onClick={() => onRetest(order)}><FlaskConical size={16} aria-hidden="true" />复测</Button></div></td> : null}</tr>)}</tbody></table></div>; }
function TableSkeleton() { return <div className={styles.tableState}><RotateCcw size={18} aria-hidden="true" />正在加载订单…</div>; }
const editableValues = (order: Order): OrderPatchFormValues => ({ priority: order.priority, promised_finish_time: toLocalDateTimeInput(order.promised_finish_time), project_ids: order.project_ids });
const toApiTimestamp = (value: string) => new Date(value).toISOString();
const toLocalDateTimeInput = (value: string) => {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};
const problemMessage = (error: unknown, fallback: string) => error instanceof ApiProblem ? error.message : error ? fallback : null;
const formatDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
const priorityLabel = (value: string) => ({ vip: "VIP", urgent: "加急", normal: "普通" }[value] ?? value);
const statusLabel = (value: string) => ({ pending: "待排程", scheduled: "已排程", blocked: "阻塞", running: "运行中", completed: "已完成" }[value] ?? value);
const priorityTone = (value: string): StatusTone => value === "vip" ? "danger" : value === "urgent" ? "warning" : "neutral";
const statusTone = (value: string): StatusTone => value === "blocked" ? "danger" : value === "scheduled" ? "info" : value === "completed" ? "success" : "neutral";
