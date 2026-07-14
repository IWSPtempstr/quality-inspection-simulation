import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { BookOpenCheck, CloudOff, FileWarning, RefreshCw, Search } from "lucide-react";
import { apiRequest } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Citation, Health, KnowledgeResult } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import styles from "@/features/knowledge/KnowledgePage.module.css";

type RequestKind = "query" | "impact";
type ResultState = { kind: RequestKind; result: KnowledgeResult } | null;

export function KnowledgePage() {
  const [question, setQuestion] = useState(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const standard = searchParams.get("standard");
    const clause = searchParams.get("clause");
    return standard ? `请核对 ${standard}${clause ? ` ${clause}` : ""} 的原文、版本和页码。` : "";
  });
  const [versionId, setVersionId] = useState("");
  const [result, setResult] = useState<ResultState>(null);
  const health = useQuery({ queryKey: queryKeys.health, queryFn: () => apiRequest<Health>("/system/health") });
  const request = useMutation({
    mutationFn: ({ kind, value }: { kind: RequestKind; value: string }) => apiRequest<KnowledgeResult>(kind === "query" ? "/knowledge/query" : "/knowledge/impact-analysis", { method: "POST", body: JSON.stringify(kind === "query" ? { query: value } : { standard_version_id: value }) }),
    onSuccess: (response, variables) => setResult({ kind: variables.kind, result: response }),
  });
  const submit = (kind: RequestKind) => {
    const value = kind === "query" ? question.trim() : versionId.trim();
    if (!value) return;
    setResult(null);
    request.mutate({ kind, value });
  };
  const retry = () => request.variables && request.mutate(request.variables);
  const errorLabel = request.variables?.kind === "impact" ? "无法完成影响分析。请检查网络后重试。" : "无法查询标准。请检查网络后重试。";

  return <>
    <PageHeader title="标准知识" description="基于版本化标准的只读查询。答案仅在服务端返回完整引用证据时显示。" />
    {health.data?.status === "degraded" ? <p className={styles.degraded} role="status"><FileWarning size={18} aria-hidden="true" />辅助检索服务降级，查询结果可能提示证据不足。</p> : null}
    {health.isError ? <p className={styles.degraded} role="status"><CloudOff size={18} aria-hidden="true" />服务健康状态暂不可用，返回内容仍须以引用证据为准。</p> : null}
    <main className={styles.grid}>
      <section className={styles.surface} aria-labelledby="knowledge-query-title">
        <h2 id="knowledge-query-title">标准查询</h2><p>检索标准条款，并核对原文和页码。</p>
        <label>标准问题<textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入需要查证的标准问题" /></label>
        <Button type="button" onClick={() => submit("query")} disabled={!question.trim() || request.isPending}>{request.isPending && request.variables?.kind === "query" ? "正在查询" : <><Search size={16} aria-hidden="true" />查询标准</>}</Button>
      </section>
      <section className={styles.surface} aria-labelledby="impact-title">
        <h2 id="impact-title">版本影响分析</h2><p>获取版本变更的只读影响说明，不会修改排程或资源。</p>
        <label>标准版本标识<input value={versionId} onChange={(event) => setVersionId(event.target.value)} placeholder="例如 CCC-2026.2" /></label>
        <Button type="button" onClick={() => submit("impact")} disabled={!versionId.trim() || request.isPending}>{request.isPending && request.variables?.kind === "impact" ? "正在分析" : <><BookOpenCheck size={16} aria-hidden="true" />分析影响</>}</Button>
      </section>
    </main>
    {request.isPending ? <section className={styles.result} aria-busy="true">正在等待服务端返回引用证据…</section> : null}
    {request.isError ? <section className={styles.error} role="alert"><span>{errorLabel}</span><Button variant="secondary" type="button" onClick={retry} aria-label={request.variables?.kind === "impact" ? "重试影响分析" : "重试标准查询"}><RefreshCw size={16} aria-hidden="true" />重试</Button></section> : null}
    {result ? <KnowledgeResultPanel result={result.result} title={result.kind === "impact" ? "影响分析结果" : "查询结果"} /> : null}
  </>;
}

function KnowledgeResultPanel({ result, title }: { result: KnowledgeResult; title: string }) {
  const cited = result.evidence_available && result.citations.length > 0 && result.citations.every(completeCitation);
  if (!cited) return <section className={styles.insufficient} role="alert"><strong>证据不足</strong><p>服务端未提供完整的标准、版本、条款、页码和原文。系统不会展示未经引用支持的结论。</p></section>;
  return <section className={styles.result} aria-labelledby="knowledge-result-title"><h2 id="knowledge-result-title">{title}</h2><p className={styles.answer}>{result.answer}</p><h3>引用证据</h3><ul className={styles.citations}>{result.citations.map((citation) => <li key={`${citation.standard_title}-${citation.version}-${citation.clause}-${citation.page}`}><strong>{citation.standard_title}</strong><span>版本 {citation.version} | 条款 {citation.clause} | 第 {citation.page} 页</span><p>{citation.content}</p></li>)}</ul></section>;
}

const completeCitation = (citation: Citation) => Boolean(citation.standard_title && citation.version && citation.clause && citation.content && Number.isInteger(citation.page) && citation.page > 0);
