# 电器产品质量检测多 Agent 仿真系统

本项目面向电器产品质量监督检验中心的日常检测队列管理场景，构建一套后端优先的多 Agent 智能协同仿真系统。系统围绕普通订单、加急订单和 VIP 订单，模拟 CCC 认证、CVC 认证和国际认证相关检测任务，并根据订单优先级、检测项目流程、设备类型、设备数量、批处理容量和检测时长生成检测队列。

当前实现基于 `/home/work/workproject2/smart-appointment-ai-agent-master` 的分层思路进行领域替换，保留 FastAPI、Agent、Service、DB 的边界设计，不复制原按摩预约业务代码。

## 当前版本快照

当前版本已经从“接口可演示原型”推进到“可验证的拟真排程原型”。系统支持订单 CRUD、复检订单、订单级检测路线、设备实例级调度、人员实例约束、前处理与跨实验室转运、排程事件心跳、运行中步骤锁定、检测完成回写、候选策略评分、结构化调度解释、通知 Agent、操作审计、排程批次持久化、数据集按时间回放导入、Agent 离线评测与在线 Trace、FAISS/RAG 检索、MCP 工具入口、LangGraph 多 Agent 编排、Jinja2 管理页，以及最小数据集、500 单数据集和 5000 单大样本数据集验证。

本仓库包含三组验证数据：

- `data/mechanism_validation/`：最小机制验证数据集，用于验证订单、队列、RAG、MCP 和 Agent 链路是否连通。
- `data/scenario_synthetic_center/`：500 单合成拟真数据集，用于常规机制验证和指标输出；订单中包含 `detection_route`，用于表达订单级检测路线和共享设备冲突。
- `data/scenario_synthetic_center_large/`：5000 单合成拟真数据集，用于较大样本压力验证；验证脚本默认对全量数据做静态校验，并抽取前 500 单跑通 API、RAG、排程和 Agent 链路。

数据集均为合成仿真数据，不代表任何真实检测中心的设备数量、检测耗时、订单分布或插队规则。

## 项目定位

检测中心的实际业务通常涉及订单接收、样品识别、认证类型判断、检测项目拆解、设备资源匹配、队列排序和过程监测。由于现阶段缺少真实设备台账、设备能力矩阵、标准检测时长和历史工时数据，本项目先通过参数化仿真方式建立可运行闭环。

仿真参数包括：

- 设备类型 `x`：如安全检测设备、电磁兼容设备、性能测试台、环境试验箱等。
- 每类设备数量 `d`：同一设备类型可配置多台设备。
- 支持项目类型 `i`：不同设备可支持不同检测项目。
- 检测时间 `t`：每个检测步骤配置仿真耗时。
- 单次容量 `n`：设备一次可检测的样品数量。

## 技术栈

- 后端框架：FastAPI
- 数据库：SQLite + SQLAlchemy
- 数据校验：Pydantic
- 多 Agent 编排：LangGraph
- RAG：OpenAI 兼容 Embedding + FAISS 优先索引 + 本地确定性 fallback
- 工具接入：独立 MCP stdio 服务 + 本地工具 fallback
- LLM：OpenAI 兼容 Chat API，可按 Agent 单独配置；当前仅异常分析 Agent 可选调用
- 前端页面：Jinja2 服务端渲染管理页
- 测试：pytest
- 运行环境：WSL2 Conda 环境 `agent-learning`

## 系统架构

```text
API Layer
  ├─ /api/orders       订单增删改查
  ├─ /api/queue        队列查询与重建
  ├─ /api/schedules    历史排程查询
  ├─ /api/scheduling   排程事件与心跳
  ├─ /api/notifications 员工通知与 SSE
  ├─ /api/simulation   仿真时钟
  ├─ /api/admin        用户权限与操作审计
  ├─ /api/monitor      队列与设备监测快照
  ├─ /api/datasets     数据集摘要与按时间回放
  ├─ /api/evaluation   Agent 离线评测与在线 Trace
  ├─ /api/knowledge    RAG 知识检索与索引重建
  ├─ /api/mcp          MCP 工具状态
  └─ /api/agent        LangGraph Agent 入口

Agent Layer
  ├─ Orchestrator              全局任务路由
  ├─ Order Manager Agent       订单管理
  ├─ Project Identifier Agent  检测项目识别
  ├─ RAG Retriever Agent       认证与设备知识检索
  ├─ Queue Scheduler Agent     队列调度
  ├─ Equipment Monitor Agent   设备状态监测
  ├─ Notification Agent        排程提醒与仿真时钟
  └─ Exception Analyzer Agent  异常与阻塞分析

Service Layer
  ├─ SimulationService   设备与检测项目仿真
  ├─ QueueService        优先级排序与排程
  ├─ SchedulingEventService 排程事件写入、去重与查询
  ├─ SchedulerHeartbeatService 心跳触发与后台消费
  ├─ SchedulingCoordinatorService queue_scheduler 统一排程入口
  ├─ ScheduleOptimizerService 候选策略评分
  ├─ NotificationService 员工提醒生成与触发
  ├─ DatasetReplayService 数据集按到达时间回放导入
  ├─ AgentEvaluationService 离线评测与阈值状态
  ├─ OpenAICompatibleLlmClient  可选异常分析增强
  ├─ McpToolClient       MCP stdio 调用与 fallback
  └─ ScheduleFormatter   持久化排程输出整理

DB Layer
  ├─ orders
  ├─ equipment
  ├─ detection_projects
  ├─ queue_events
  ├─ scheduling_events
  ├─ schedule_runs
  ├─ schedule_steps
  ├─ dataset_replay_runs
  ├─ dataset_replay_items
  ├─ agent_traces
  ├─ agent_trace_steps
  ├─ notifications
  ├─ users
  └─ audit_logs
```

系统采用混合型多 Agent 架构。Orchestrator 负责统一入口、任务路由和全局状态控制；子 Agent 在明确依赖关系下允许定向通信，例如 Queue Scheduler Agent 可向 Equipment Monitor Agent 请求设备状态，Project Identifier Agent 可向 RAG Retriever Agent 请求认证知识上下文。

当前 Agent 主要是 LangGraph 状态图中的确定性流程节点。`queue_scheduler` 是统一排程协调节点，API 手动重排、Agent 重排和心跳自动重排均通过它进入候选策略分析、排程计算、持久化和通知生成流程，并输出候选策略差异、瓶颈资源和 SLA 风险摘要。`exception_analyzer` 支持在配置 API Key 后调用 OpenAI 兼容 Chat API，用于解释阻塞、延期和瓶颈；调用失败时返回确定性结构化 fallback。其他 Agent 的模型配置已具备读取能力，但尚未把自然语言推理作为核心决策依据。

## 排程机制

当前调度器采用规则驱动的非抢占式排程，核心约束如下：

- 优先级规则为 `vip > urgent > normal`，但仅对已经释放到队列中的订单生效。
- 显式提供 `arrival_time` 的订单按到达时间释放；未提供 `arrival_time` 的 API 订单视为同一待排批次，以保留日常手工录入场景下的优先级排序行为。
- 同一检测项目可绑定多个设备实例，排程步骤会记录具体 `equipment_id`，设备数量 `d` 会直接影响并行能力。
- 单台设备单次容量 `n` 会影响 `required_batches` 和步骤持续时间。
- 检测步骤按 `sequence` 顺序执行，后续步骤不能早于前序步骤完成。
- 人员采用具体员工实例建模，每个检测步骤至少分配 1 名符合技能、角色和实验室区域要求的员工；部分步骤可配置 3 名及以上员工同时在场。
- 支持 `exclusive`、`shared_supervision`、`setup_only` 三类人员占用模式。共享监管限定在同一实验室区域、同技能范围和员工并行上限内。
- 首个检测步骤前可插入样品前处理步骤；相邻步骤跨实验室区域时自动插入样品转运步骤。
- 设备准备/换型时间、维护窗口、模拟故障窗口、周末、午休、工作日结束时间和耗材日配额会参与排程避让。
- 系统输出 `sla_status`、`delay_minutes`、平均等待时间、设备利用率、VIP SLA 达成率、加急延误率、人员阻塞、转运等待和阻塞原因分布。

该排程仍属于规则仿真和候选策略评分，不声明全局数学最优；默认采用非抢占式重排，已开始检测步骤在业务定义上不应被中断，当前代码层面的自动重排主要面向未开始订单和未开始步骤。

## 事件驱动重排

系统新增 `scheduling_events` 事件表，订单创建、修改、取消会自动写入事件；设备故障、人员不可用、耗材不足、维护变更、检测完成、样品转运和手动重排等突发状况可通过事件 API 写入。事件状态包括 `pending`、`processing`、`done`、`ignored` 和 `failed`。

事件使用 `fingerprint` 和防抖窗口做合并处理，默认 30 秒内的同类事件会被标记为 `ignored`。`SchedulerHeartbeatService` 提供手动触发 API，也会在 FastAPI 启动时按 `SCHEDULER_HEARTBEAT_ENABLED` 和 `SCHEDULER_HEARTBEAT_INTERVAL_SECONDS` 启动后台心跳。高严重度事件（默认 `critical,high`）通过事件 API 写入后会立即触发一次心跳处理。

`queue_scheduler` 是统一排程入口。它读取待处理事件和当前订单，调用 `ScheduleOptimizerService` 生成候选策略，包括 `priority_fifo`、`earliest_due_date`、`shortest_processing_time`、`bottleneck_resource_first` 和 `hybrid_weighted`。候选排程按阻塞订单数、VIP/加急/普通延期分钟、平均等待、设备空闲惩罚、人员阻塞和转运等待进行评分，默认选择评分最低的方案并持久化为 `schedule_runs` 和 `schedule_steps`。

## 数据集按时间回放

数据集不再只作为静态验证摘要展示。系统新增 `dataset_replay_runs` 和 `dataset_replay_items`，可将 `data/` 目录下的数据集按订单 `arrival_time` 加速回放导入系统。启动回放时，系统读取指定数据集的订单文件，按到达时间排序，并建立待导入清单；正式订单表在启动后仍为空，只有当用户执行单步导入或手动 Tick 时，已到达订单才会写入 `orders`。

回放流程如下：

1. 选择数据集并创建回放批次。
2. 将仿真时钟设置为数据集最早订单到达时间。
3. 单步导入下一条订单，或按倍率推进 Tick。
4. 将到达时间小于等于当前仿真时间的订单写入正式订单表。
5. 为导入订单写入 `order_created` 排程事件。
6. 每个 Tick 结束后触发一次 `scheduler_heartbeat`，由 `queue_scheduler` 统一重排。
7. 生成通知并更新仪表盘、队列页和通知页。

默认倍率为 `1 秒真实时间 = 30 分钟仿真时间`。第一版不在后端启动长期定时器，主要通过 API、Swagger 或测试脚本调用“单步导入”和“手动 Tick”接口来确定性推进；暂停状态下 Tick 不推进。当前仪表盘不再保留数据集回放控制台或静态数据集摘要表。`scenario_synthetic_center_large` 包含 5000 单，回放接口默认最多导入前 500 单，完整压力测试仍建议使用验证脚本。

## 执行状态与审计

排程步骤支持运行中和完成回写。`/api/schedules/steps/{step_id}/running` 会把对应检测步骤和订单标记为 `running`，并设置 `locked=true`；后续自动重排会保留该订单已锁定的步骤，只重排未开始订单和未开始步骤。`/api/schedules/steps/{step_id}/complete` 会记录实际完成时间，并在订单所有检测步骤完成后把订单状态回写为 `completed`。

复检通过 `/api/orders/{order_id}/retest` 创建新订单，记录 `parent_order_id` 和 `retest_reason`，并写入 `retest_required` 排程事件。系统同时提供简单的 header 权限模型，默认角色为 `admin`；可通过 `X-User-Role` 和 `X-User-Id` 模拟 `admin/scheduler/operator/viewer`。订单、排程、事件、通知和执行回写会写入 `audit_logs`，用于演示操作审计。

## Agent 评价体系

系统新增离线评测与在线 Trace 两类评价能力。离线评测使用 `data/evaluation/agent_eval_cases.jsonl` 中的 JSONL 标准任务集，对响应质量、轨迹状态和执行效率进行评分；在线 Trace 在每次 `/api/agent/run` 后记录 `trace_id`、Agent 路径、handoff、工具调用、节点耗时、Token 使用占位和错误信息。

当前评价指标包括：

- 系统级：业务正确性、排程质量、系统效率、稳定性和可观测性。
- Agent 级：Orchestrator 路由准确率、RAG Hit@K、Queue Scheduler 排程可行率、Equipment Monitor 工具调用成功率、Notification Agent 触发准确率、Exception Analyzer 解释质量和 fallback 触发率。
- 离线评测：响应质量使用规则断言模拟 LLMJudge 输出，语义类指标后续可替换为真实 LLMJudge；轨迹状态会对比 `visited_agents` 与 `handoffs`；效率会检查端到端延迟和 handoff 数量。
- 在线阈值：默认监控 Agent 成功率、轨迹符合率、MCP 成功率、RAG Hit@3、500 单重排耗时、约束违规数、LLM fallback 连续次数和 Token 预算。

## 算法替代路线

当前规则排程和候选评分仍作为 baseline。可替代算法路线见 [docs/scheduling_algorithm_options.md](docs/scheduling_algorithm_options.md)，重点包括 CP-SAT/约束规划、MILP、元启发式算法、滚动时域重排和强化学习。第一优先级建议是 CP-SAT + 滚动时域，因为它更容易表达设备互斥、人员容量、维护窗口、耗材容量和运行中步骤锁定。

## 目录结构

```text
project/
├── agents/              # LangGraph 多 Agent 编排
├── api/                 # FastAPI 路由
├── config/              # 应用配置
├── db/                  # SQLAlchemy 模型与仓储
├── domain/              # Pydantic schema 与枚举
├── mcp_server/          # MCP 模拟工具服务
├── rag/                 # RAG 检索、索引与知识库
├── services/            # 仿真、调度、MCP 和格式化服务
├── data/
│   ├── evaluation/                    # Agent 离线评测 JSONL
│   ├── mechanism_validation/          # 最小机制验证数据集
│   ├── scenario_synthetic_center/     # 500 单合成拟真数据集
│   └── scenario_synthetic_center_large/ # 5000 单大样本合成数据集
├── docs/                # 算法路线和项目设计文档
├── tests/               # pytest 测试
├── web/                 # Jinja2 管理页
├── app.py               # FastAPI 应用入口
├── requirements.txt
└── README.md
```

## 快速开始

确认 Conda 环境：

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python --version
```

安装依赖：

```bash
cd /home/work/workproject2/project
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pip install -r requirements.txt
```

配置本地环境变量：

```bash
cd /home/work/workproject2/project
cp .env.example .env
```

`.env` 已被 `.gitignore` 排除，不应提交真实密钥。进程环境变量优先级高于 `.env` 文件，可用于临时覆盖。

启动服务：

```bash
cd /home/work/workproject2/project
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m uvicorn app:app --reload --port 8002
```

启动后访问：

- 管理页：`http://127.0.0.1:8002/`
- Swagger：`http://127.0.0.1:8002/docs`
- ReDoc：`http://127.0.0.1:8002/redoc`

## 环境变量

```bash
export LLM_PROVIDER=openai-compatible
export LLM_API_KEY=your-chat-key
export LLM_BASE_URL=https://api.example.com/v1
export LLM_MODEL=qwen-plus
export LLM_ENABLE_THINKING=false
export EMBEDDING_PROVIDER=openai-compatible
export EMBEDDING_API_KEY=your-key
export EMBEDDING_BASE_URL=https://api.example.com/v1
export EMBEDDING_MODEL=text-embedding-v3
export RAG_INDEX_DIR=/home/work/workproject2/project/rag/index
export OPERATIONS_CONSTRAINTS_PATH=/home/work/workproject2/project/data/scenario_synthetic_center/operations_constraints.json
export MCP_ADAPTER_TYPE=simulation
export MCP_SERVER_COMMAND=/root/anaconda3/envs/agent-learning/bin/python
export MCP_SERVER_ARGS="-m mcp_server.simulation_server"
export SCHEDULER_HEARTBEAT_ENABLED=true
export SCHEDULER_HEARTBEAT_INTERVAL_SECONDS=30
export SCHEDULER_DEBOUNCE_SECONDS=30
export SCHEDULER_IMMEDIATE_SEVERITIES=critical,high
export SCHEDULER_DEFAULT_STRATEGY=hybrid_weighted
```

关键配置说明：

- `LLM_*`：默认 Chat 模型配置，当前主要供异常分析 Agent 使用。
- `AGENT_<AGENT_NAME>_*`：按 Agent 覆盖模型、温度、最大 token 和 thinking 开关，例如 `AGENT_EXCEPTION_ANALYZER_MODEL`。
- `EMBEDDING_*`：RAG 向量化配置。未配置 `EMBEDDING_API_KEY` 时，系统会使用本地确定性向量 fallback，便于离线测试。
- `OPERATIONS_CONSTRAINTS_PATH`：合成拟真数据集中的班次、维护、停机等运营约束文件。
- `MCP_ADAPTER_TYPE`：MCP 工具适配器标签，当前可用值以 `simulation` 为主，真实 LIMS/设备台账适配器仍是后续扩展。
- `SCHEDULER_*`：排程事件防抖、后台心跳、立即触发严重度和默认候选策略配置。

对于 Qwen 推理模型，若通过普通 chat completion 接口返回业务 JSON 或短文本，建议将对应 Agent 的 `*_ENABLE_THINKING=false`。本项目只在模型名称包含 `qwen` 时向请求体写入 `enable_thinking` 字段。

## API 示例

创建订单：

```bash
curl -X POST http://127.0.0.1:8002/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "order_type": "vip",
    "sample_name": "家用电器样品",
    "sample_quantity": 2,
    "certification_type": "ccc"
  }'
```

重建队列并持久化排程：

```bash
curl -X POST http://127.0.0.1:8002/api/queue/rebuild
```

查询最新队列：

```bash
curl http://127.0.0.1:8002/api/queue
```

查询历史排程：

```bash
curl http://127.0.0.1:8002/api/schedules
```

写入突发排程事件：

```bash
curl -X POST http://127.0.0.1:8002/api/scheduling/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "equipment_offline",
    "severity": "high",
    "entity_type": "equipment",
    "entity_id": "safety_tester-1",
    "payload": {"reason": "simulated failure"}
  }'
```

手动触发一次心跳消费：

```bash
curl -X POST http://127.0.0.1:8002/api/scheduling/heartbeat
curl http://127.0.0.1:8002/api/scheduling/heartbeat/status
```

查询可回放数据集并启动按时间回放：

```bash
curl http://127.0.0.1:8002/api/datasets
curl http://127.0.0.1:8002/api/datasets/scenario_synthetic_center/summary

curl -X POST http://127.0.0.1:8002/api/datasets/scenario_synthetic_center/replay/start \
  -H "Content-Type: application/json" \
  -d '{
    "speed_minutes_per_second": 30,
    "max_orders": 500,
    "reset_runtime": true
  }'
```

推进、暂停和查询回放批次：

```bash
curl -X POST http://127.0.0.1:8002/api/datasets/replay/{run_id}/step
curl -X POST http://127.0.0.1:8002/api/datasets/replay/{run_id}/tick
curl -X POST http://127.0.0.1:8002/api/datasets/replay/{run_id}/pause
curl -X POST http://127.0.0.1:8002/api/datasets/replay/{run_id}/resume
curl http://127.0.0.1:8002/api/datasets/replay/{run_id}
curl -N http://127.0.0.1:8002/api/datasets/replay/{run_id}/stream
```

闭环异常事件：

```bash
curl -X PATCH http://127.0.0.1:8002/api/scheduling/events/{event_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"status": "done", "resolution_note": "已人工确认并关闭"}'
```

比较候选排程策略：

```bash
curl -X POST http://127.0.0.1:8002/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task_type": "analyze_schedule_options", "payload": {}}'
```

RAG 检索：

```bash
curl -X POST http://127.0.0.1:8002/api/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"query": "CCC 强制性认证 安全检测", "top_k": 3}'
```

重建 RAG 索引：

```bash
curl -X POST http://127.0.0.1:8002/api/knowledge/reindex
```

查询 MCP 状态：

```bash
curl http://127.0.0.1:8002/api/mcp/status
```

当前 MCP 客户端仍会启动 stdio 服务用于独立工具连通性验证；涉及队列快照和设备预约这类需要共享应用状态的工具，使用应用内 `LocalSimulationToolClient` 执行，以避免独立 MCP 进程持有一份空的队列状态。`/api/mcp/status` 中的 `stateful_tools_mode` 会标识这一点。

运行 Agent：

```bash
curl -X POST http://127.0.0.1:8002/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task_type": "query_queue", "payload": {}}'
```

运行离线评测并查询在线 Trace：

```bash
curl -X POST http://127.0.0.1:8002/api/evaluation/offline/run \
  -H "Content-Type: application/json" \
  -d '{"dataset_path": "data/evaluation/agent_eval_cases.jsonl", "limit": 3}'

curl http://127.0.0.1:8002/api/evaluation/traces
curl http://127.0.0.1:8002/api/evaluation/traces/{trace_id}
curl http://127.0.0.1:8002/api/evaluation/thresholds/status
```

标记检测步骤运行中与完成：

```bash
curl -X PATCH http://127.0.0.1:8002/api/schedules/steps/{step_id}/running \
  -H "Content-Type: application/json" \
  -H "X-User-Role: operator" \
  -d '{"note": "开始检测"}'

curl -X PATCH http://127.0.0.1:8002/api/schedules/steps/{step_id}/complete \
  -H "Content-Type: application/json" \
  -H "X-User-Role: operator" \
  -d '{"note": "检测完成"}'
```

创建复检订单：

```bash
curl -X POST http://127.0.0.1:8002/api/orders/{order_id}/retest \
  -H "Content-Type: application/json" \
  -d '{"reason": "检测结果复核不一致"}'
```

查询甘特图、监控报告和审计：

```bash
curl http://127.0.0.1:8002/api/schedules/{run_id}/gantt
curl http://127.0.0.1:8002/api/monitor/report
curl http://127.0.0.1:8002/api/admin/audit-logs
curl http://127.0.0.1:8002/api/admin/users
```

查询通知：

```bash
curl http://127.0.0.1:8002/api/notifications
curl -N http://127.0.0.1:8002/api/notifications/stream
```

## 管理页

- `/`：检测队列仪表盘
- `/orders`：订单管理
- `/queue`：队列与排程
- `/knowledge`：知识库检索
- `/agents`：Agent 执行轨迹
- `/notifications`：员工提醒与仿真通知

管理页通过现有 API 获取数据，不引入 Node、Vue 或 React 构建链。

## 测试

```bash
cd /home/work/workproject2/project
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest -q -s
```

合成数据集验证：

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/validate_synthetic_center_dataset.py
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/validate_large_synthetic_center_dataset.py
```

大样本数据集位于 `data/scenario_synthetic_center_large/`，包含 2026-06-01 至 2026-11-30 周期内的 5000 条合成订单。大样本验证脚本会对 5000 条订单做静态一致性校验，并默认抽取前 500 条跑通 API、RAG、排程和 Agent 链路。

最近一次本地验证命令：

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest -q -s
```

验证结果为 `63 passed, 3 warnings`。如修改调度、RAG、MCP 或数据集生成逻辑，应同时运行对应的数据集验证脚本。

当前测试覆盖：

- 订单优先级：`vip > urgent > normal`
- 同优先级按创建时间排序
- 多步骤检测流程顺序
- 订单级 `detection_route` 覆盖默认认证流程
- 旧版 SQLite 订单表自动补齐 `detection_route` 列
- 检测耗时按 `t_min/t_mode/t_max` 生成浮动值
- 不同订单共享设备类型时的资源冲突排队
- 设备容量与批处理计算
- 设备不可用时的阻塞状态
- RAG 索引持久化、重建和状态查询
- RAG 检索命中
- MCP stdio 工具调用与本地 fallback
- 排程批次和排程步骤持久化
- Jinja2 管理页渲染
- FastAPI 订单创建与队列重建
- LangGraph Orchestrator 到子 Agent 的 handoff 轨迹
- 设备实例级并行排程
- 到达时间感知的非抢占式优先级、维护窗口避让、工作日结束时间约束、SLA 状态和延期分钟数
- 排程指标：平均等待、设备利用率、VIP SLA 达成率、加急延误率、阻塞原因分布
- 人员实例约束、多人设备、共享监管、样品前处理、跨实验室转运、设备准备时间和耗材日配额
- 排程事件写入、去重、防抖、手动心跳、高严重度立即触发、候选策略评分和 queue_scheduler 统一入口
- 数据集列表、摘要、按时间回放启动、Tick 导入、单步导入、暂停续跑、权限拦截和 SSE 状态快照
- Notification Agent、通知持久化、仿真时钟推进和 SSE 接口
- 运行中步骤锁定、检测完成回写、复检订单、设备预约甘特图、监控报告、权限拦截和操作审计
- 异常分析 Agent 的 LLM 失败 fallback
- Agent 在线 Trace 持久化、离线 JSONL 评测、响应质量/轨迹状态/效率评分和阈值状态查询

## 当前完成度

已完成：

- 后端项目骨架与分层结构
- 领域模型、订单类型、认证类型、队列状态、设备状态
- SQLite 持久化模型与基础仓储
- 订单创建、查询、修改、取消接口
- 检测设备仿真与认证项目仿真流程
- 队列排序、队列重建、阻塞识别
- 设备实例级排程：排程步骤记录具体 `equipment_id`，同类多台设备可并行处理
- 运营约束接入：订单到达时间、承诺完成时间、人员实例、班次、午休、维护/故障窗口、工作日结束时间、前处理、转运、准备时间和耗材日配额参与排程
- SLA 与运营指标：准时/延期状态、延期分钟数、等待时间、设备利用率、人员阻塞、转运等待和阻塞原因分布
- 排程事件队列：订单变化和突发状况写入 `scheduling_events`，支持去重、防抖、状态追踪和关联排程批次
- 心跳重排机制：支持后台周期消费、手动触发、高严重度事件即时触发和并发锁控制
- 候选策略评分：支持多种规则策略比较，并记录 `selected_strategy` 和 `candidate_scores`
- 结构化调度解释：输出候选策略排名、瓶颈资源、SLA 风险、阻塞原因和建议动作
- 执行状态流转：支持步骤运行中锁定、检测完成回写、复检订单和运行中订单重排保留
- 权限与审计：提供 `admin/scheduler/operator/viewer` 模拟角色、操作审计日志和用户权限查询
- RAG 索引重建、保存、加载和检索
- MCP stdio 独立服务入口与本地 fallback
- MCP 适配器标签：当前为 `simulation`，用于后续替换真实工具源
- 排程批次和步骤持久化
- 数据集回放：支持列出数据集、查看摘要、按 `arrival_time` 建立回放批次、单步导入、手动 Tick、暂停、续跑和 SSE 状态快照
- Notification Agent、通知表、仿真时钟、SSE 通知流和通知管理 API
- Jinja2 管理页：仪表盘、订单、队列、知识库、Agent轨迹、通知面板
- LangGraph 多 Agent 编排与异常分析 Agent 可选 LLM 调用
- Agent 评价体系：支持 JSONL 离线评测、在线 Trace 入库、节点耗时记录、工具调用记录和阈值状态查询
- FastAPI 接口与自动化测试

当前限制：

- 当前环境已安装 `faiss-cpu`，RAG 索引优先使用 FAISS；若其他环境未安装 FAISS，会自动使用 numpy fallback。
- MCP 独立服务目前封装的是仿真工具，还未接入真实实验室系统。
- `MCP_ADAPTER_TYPE` 当前是适配器类型标识，不代表已经连通真实 LIMS、设备台账或工时系统。
- 合成数据集用于机制验证和压力测试，不代表某真实检测中心的设备数量、检测耗时、订单到达分布或插队规则。
- 数据集回放验证的是订单释放、事件触发和心跳重排机制，不代表真实检测中心的实时接单节奏或生产排程效果。
- 调度器已使用设备实例、人员实例、前处理、转运、耗材、到达时间、SLA、维护窗口和工作日结束时间，但仍是规则排程与候选评分，不是数学优化求解器。
- 非抢占式约束已覆盖运行中步骤锁定和未开始任务重排；暂停、续跑、人工复核审批流仍是后续扩展。
- 高严重度事件通过 API 写入后会立即触发一次心跳；后台周期心跳只在 FastAPI 生命周期启动后运行，测试和脚本仍以手动触发为主，以保证验证结果确定。
- MCP stdio 服务已可独立启动，但需要共享应用状态的工具当前仍通过应用内 fallback 执行；真实外部 MCP 服务适配需要单独设计状态同步或数据库访问边界。
- 除 `exception_analyzer` 外，其他 Agent 当前仍以确定性流程为主，模型配置属于后续增强入口。
- 当前 LLMJudge 为规则断言 fallback，用于离线开发和稳定测试；真实 LLMJudge、云端观测面板和 Token 精细计费仍是后续可接入能力。
- 前端管理页以服务端渲染和少量原生 JS 为主，尚未加入真实登录态下的权限控制和复杂交互组件。
- 设备状态、检测时间、检测项目仍是仿真种子数据。
- 尚未接入真实 LIMS、设备台账、检测标准库或历史工时数据。

## 后续步骤

1. 将 CP-SAT/滚动时域求解器接入 `ScheduleOptimizerService`，与当前规则 baseline 并行对比。
2. 增加检测执行层面的暂停、续跑、返工审批、报告复核等更完整闭环。
3. 将 MCP 工具替换为真实设备台账、LIMS、检测标准库、人员考勤和工时服务适配器，并明确状态同步方式。
4. 增加权限模型的真实登录、角色管理和操作审计导出。
