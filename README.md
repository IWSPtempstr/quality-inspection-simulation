# 电器产品质量检测多 Agent 仿真系统

本项目面向电器产品质量监督检验中心的日常检测队列管理场景，构建一套后端优先的多 Agent 智能协同仿真系统。系统围绕普通订单、加急订单和 VIP 订单，模拟 CCC 认证、CVC 认证和国际认证相关检测任务，并根据订单优先级、检测项目流程、设备类型、设备数量、批处理容量和检测时长生成检测队列。

当前实现基于 `/home/work/workproject2/smart-appointment-ai-agent-master` 的分层思路进行领域替换，保留 FastAPI、Agent、Service、DB 的边界设计，不复制原按摩预约业务代码。

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
  ├─ /api/monitor      队列与设备监测快照
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
  └─ Exception Analyzer Agent  异常与阻塞分析

Service Layer
  ├─ SimulationService   设备与检测项目仿真
  ├─ QueueService        优先级排序与排程
  ├─ OpenAICompatibleLlmClient  可选异常分析增强
  ├─ McpToolClient       MCP stdio 调用与 fallback
  └─ ScheduleFormatter   持久化排程输出整理

DB Layer
  ├─ orders
  ├─ equipment
  ├─ detection_projects
  ├─ queue_events
  ├─ schedule_runs
  └─ schedule_steps
```

系统采用混合型多 Agent 架构。Orchestrator 负责统一入口、任务路由和全局状态控制；子 Agent 在明确依赖关系下允许定向通信，例如 Queue Scheduler Agent 可向 Equipment Monitor Agent 请求设备状态，Project Identifier Agent 可向 RAG Retriever Agent 请求认证知识上下文。

当前 Agent 主要是 LangGraph 状态图中的确定性流程节点。`exception_analyzer` 支持在配置 API Key 后调用 OpenAI 兼容 Chat API，用于解释阻塞、延期和瓶颈；调用失败时返回确定性 fallback。其他 Agent 的模型配置已具备读取能力，但尚未把自然语言推理作为核心决策依据。

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
│   ├── mechanism_validation/          # 最小机制验证数据集
│   ├── scenario_synthetic_center/     # 500 单合成拟真数据集
│   └── scenario_synthetic_center_large/ # 5000 单大样本合成数据集
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
```

关键配置说明：

- `LLM_*`：默认 Chat 模型配置，当前主要供异常分析 Agent 使用。
- `AGENT_<AGENT_NAME>_*`：按 Agent 覆盖模型、温度、最大 token 和 thinking 开关，例如 `AGENT_EXCEPTION_ANALYZER_MODEL`。
- `EMBEDDING_*`：RAG 向量化配置。未配置 `EMBEDDING_API_KEY` 时，系统会使用本地确定性向量 fallback，便于离线测试。
- `OPERATIONS_CONSTRAINTS_PATH`：合成拟真数据集中的班次、维护、停机等运营约束文件。
- `MCP_ADAPTER_TYPE`：MCP 工具适配器标签，当前可用值以 `simulation` 为主，真实 LIMS/设备台账适配器仍是后续扩展。

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

## 管理页

- `/`：检测队列仪表盘
- `/orders`：订单管理
- `/queue`：队列与排程
- `/knowledge`：知识库检索
- `/agents`：Agent 执行轨迹

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

当前测试覆盖：

- 订单优先级：`vip > urgent > normal`
- 同优先级按创建时间排序
- 多步骤检测流程顺序
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
- 异常分析 Agent 的 LLM 失败 fallback

## 当前完成度

已完成：

- 后端项目骨架与分层结构
- 领域模型、订单类型、认证类型、队列状态、设备状态
- SQLite 持久化模型与基础仓储
- 订单创建、查询、修改、取消接口
- 检测设备仿真与认证项目仿真流程
- 队列排序、队列重建、阻塞识别
- 设备实例级排程：排程步骤记录具体 `equipment_id`，同类多台设备可并行处理
- 运营约束接入：订单到达时间、承诺完成时间、维护/故障窗口和工作日结束时间参与排程
- SLA 与运营指标：准时/延期状态、延期分钟数、等待时间、设备利用率和阻塞原因分布
- RAG 索引重建、保存、加载和检索
- MCP stdio 独立服务入口与本地 fallback
- MCP 适配器标签：当前为 `simulation`，用于后续替换真实工具源
- 排程批次和步骤持久化
- Jinja2 管理页：仪表盘、订单、队列、知识库、Agent轨迹
- LangGraph 多 Agent 编排与异常分析 Agent 可选 LLM 调用
- FastAPI 接口与自动化测试

当前限制：

- FAISS 在当前环境未安装时会自动使用 numpy fallback；安装 `faiss-cpu` 后可切换为 FAISS 后端。
- MCP 独立服务目前封装的是仿真工具，还未接入真实实验室系统。
- `MCP_ADAPTER_TYPE` 当前是适配器类型标识，不代表已经连通真实 LIMS、设备台账或工时系统。
- 合成数据集用于机制验证和压力测试，不代表某真实检测中心的设备数量、检测耗时、订单到达分布或插队规则。
- 调度器已使用设备实例、到达时间、SLA、维护窗口和工作日结束时间，但仍是规则排程；尚未实现人员技能容量、跨实验室转运、样品前处理和复杂优化算法。
- 除 `exception_analyzer` 外，其他 Agent 当前仍以确定性流程为主，模型配置属于后续增强入口。
- 前端管理页以服务端渲染和少量原生 JS 为主，尚未加入权限控制和复杂交互组件。
- 设备状态、检测时间、检测项目仍是仿真种子数据。
- 尚未接入真实 LIMS、设备台账、检测标准库或历史工时数据。

## 后续步骤

1. 补齐人员、班次、午休、周末和维护约束的完整资源排程逻辑。
2. 增强管理页指标展示，形成 500 单合成数据的验证报告。
3. 扩充异常分析 Agent 的提示词、结构化输出和回归测试。
4. 将 MCP 工具替换为真实设备台账、LIMS、检测标准库和工时服务适配器。
5. 增加订单执行状态流转、设备预约甘特图、异常事件闭环、用户权限和操作审计。
