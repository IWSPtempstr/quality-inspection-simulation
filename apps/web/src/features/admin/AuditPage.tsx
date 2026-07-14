import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ClipboardList, RefreshCw, Sparkles } from "lucide-react";
import { apiRequest } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AuditFilterSuggestion, AuditLog, Page } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import styles from "@/features/admin/AdminPages.module.css";

export function AuditPage() {
  const audit = useQuery({ queryKey: queryKeys.audit, queryFn: () => apiRequest<Page<AuditLog>>("/audit-logs") });
  const [query, setQuery] = useState("");
  const [suggestion, setSuggestion] = useState<AuditFilterSuggestion | null>(null);
  const [applied, setApplied] = useState(false);
  const suggest = useMutation({ mutationFn: () => apiRequest<AuditFilterSuggestion>("/audit-logs/filter-suggestions", { method: "POST", body: JSON.stringify({ query }) }), onSuccess: (result) => { setSuggestion(result); setApplied(false); } });
  const items = applied && suggestion ? audit.data?.items.filter((item) => suggestion.filters.every((filter) => filter.field !== "action" || item.action.includes(filter.value))) ?? [] : audit.data?.items ?? [];
  return <><PageHeader title="审计" description="不可变更的服务端审计记录，仅供查看。" /><section className={styles.surface} aria-labelledby="audit-title"><div className={styles.heading}><div><h2 id="audit-title">审计记录</h2><p>记录参与者、动作和时间；此页面不提供编辑、删除或导出操作。</p></div><span>{audit.data?.total ?? "-"} 项</span></div><div className={styles.assistant}><label>审计辅助检索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：查找今天与候选排程有关的记录" aria-label="审计辅助检索问题" /></label><Button variant="secondary" type="button" onClick={() => suggest.mutate()} disabled={!query.trim() || suggest.isPending}><Sparkles size={16} aria-hidden="true" />{suggest.isPending ? "正在生成建议" : "获取筛选建议"}</Button>{suggestion ? <div className={styles.assistantResult}><p>{suggestion.explanation}</p>{suggestion.filters.map((filter, index) => <label key={`${filter.field}-${index}`}>{filter.field}<input value={filter.value} onChange={(event) => setSuggestion({ ...suggestion, filters: suggestion.filters.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item) })} aria-label={`编辑筛选 ${filter.field}`} /></label>)}<Button variant="secondary" type="button" onClick={() => setApplied(true)}>应用可见筛选</Button><small>筛选建议不会修改、删除或补写审计记录。</small></div> : null}</div>{audit.isLoading ? <div className={styles.state} aria-busy="true">正在加载审计记录…</div> : audit.isError ? <div className={styles.state} role="alert">无法加载审计记录。请检查网络后重试。<Button variant="secondary" type="button" onClick={() => audit.refetch()} aria-label="重试加载审计记录"><RefreshCw size={16} aria-hidden="true" />重试</Button></div> : !items.length ? <div className={styles.state}><ClipboardList size={20} aria-hidden="true" />当前没有符合可见筛选条件的审计记录。</div> : <div className={styles.tableWrap}><table><thead><tr><th>记录编号</th><th>参与者</th><th>动作</th><th>时间</th><th>关联信息</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.id}</td><td>{item.actor_id}</td><td><strong>{item.action}</strong></td><td>{formatDate(item.created_at)}</td><td>{Object.entries(item.detail).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "-"}</td></tr>)}</tbody></table></div>}</section></>;
}

const formatDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
