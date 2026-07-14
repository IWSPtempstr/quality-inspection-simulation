<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## LLM Agent 增强

### 核心原则
LLM **不直接写入订单、不直接决定排程、不直接修改资源状态**。所有写操作仍走确定性 API 和权限校验。

### v1 能力（只读解释与文案增强）

| 能力 | Agent | Task Type | 权限 |
|------|-------|-----------|------|
| RAG 回答合成 | rag_retriever | `search_knowledge` | `schedule:read` |
| 排程解释 | queue_scheduler | `explain_schedule` | `schedule:read` |
| 结构化异常分析 | exception_analyzer | `analyze_exception` | `schedule:read` |
| 通知文案增强 | notification_agent | `generate_notifications` | `schedule:write` |

### v2 能力（人机确认的业务辅助输入）

| 能力 | Agent | Task Type | 权限 |
|------|-------|-----------|------|
| 自然语言订单草稿 | order_manager | `draft_order_from_text` | `orders:read` |
| 检测项目推荐 | project_identifier | `identify_projects` | `schedule:read` |
| 自然语言任务路由 | orchestrator | `route_user_query` | `schedule:read` |

**v2 安全约束：**
- `draft_order_from_text` 只生成草稿不写入 DB，需人工确认后通过 `create_order` 创建
- `route_user_query` 只返回推荐不自动执行，写操作即使被识别也不会触发
- `identify_projects` 推荐结果与确定性认证流程交叉校验，必检项目不可删除

### Fallback 机制
- 未配置 LLM API Key 时，所有 Agent 自动使用确定性逻辑（规则/模板）。
- LLM 调用失败时自动降级为 deterministic fallback。
- `mode` 字段标识：`"llm"` 或 `"deterministic_fallback"`。

### 配置
```bash
# 全局 LLM 配置（所有 Agent 共享默认值）
LLM_PROVIDER=openai-compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 按 Agent 独立覆盖（v1 + v2）
AGENT_RAG_RETRIEVER_MODEL=gpt-4o-mini
AGENT_QUEUE_SCHEDULER_MODEL=gpt-4o
AGENT_EXCEPTION_ANALYZER_MODEL=deepseek-v4-pro
AGENT_ORDER_MANAGER_MODEL=gpt-4o-mini
AGENT_PROJECT_IDENTIFIER_MODEL=gpt-4o-mini
AGENT_ORCHESTRATOR_MODEL=gpt-4o-mini
```

### API 示例

**v1 — RAG 回答合成：**
```json
POST /api/agent/run
{"task_type": "search_knowledge", "payload": {"query": "CCC安全检测需要哪些项目"}}
```

**v1 — 排程解释：**
```json
POST /api/agent/run
{"task_type": "explain_schedule", "payload": {}}
```

**v2 — 自然语言订单草稿：**
```json
POST /api/agent/run
{"task_type": "draft_order_from_text", "payload": {"user_text": "为温控开关创建VIP CCC检测订单，200个样品，下周五前完成"}}
// 响应: { order_draft, missing_fields, field_confidence, confirmation_required, mode }
```

**v2 — 任务路由：**
```json
POST /api/agent/run
{"task_type": "route_user_query", "payload": {"user_query": "帮我看下当前队列有没有延期的订单"}}
// 响应: { recommended_task_type, target_agent, confidence, suggested_payload, needs_clarification }
```

**v2 — 项目推荐（扩展 identify_projects）：**
```json
POST /api/agent/run
{"task_type": "identify_projects", "payload": {"certification_type": "ccc", "sample_description": "家用电器电源模块，需要安全检测和EMC检测", "product_category": "家用电器"}}
// 响应: { detection_flow, recommended_projects, required_projects, optional_projects, risk_notes }
```

### 离线评测
```bash
POST /api/evaluation/run
{"dataset_path": "data/evaluation/agent_eval_cases_v2.jsonl"}
```
评测集含 30 条样本，覆盖 v1+v2 所有能力。报告包含字段准确率、路由准确率、fallback 率、平均延迟和 token 消耗。

### 架构
- `services/llm_client.py::OpenAICompatibleLlmClient.chat_json()` — 通用 JSON 模式 LLM 调用
- `agents/graph.py::AgentGraphRunner._llm_call()` — 统一的 LLM 调用 + fallback 辅助方法
- Token Usage 通过 `llm_metadata` 写入 Agent Trace

### 架构
- `services/llm_client.py::OpenAICompatibleLlmClient.chat_json()` — 通用 JSON 模式 LLM 调用
- `agents/graph.py::AgentGraphRunner._llm_call()` — 统一的 LLM 调用 + fallback 辅助方法
- Token Usage 通过 `llm_metadata` 写入 Agent Trace
