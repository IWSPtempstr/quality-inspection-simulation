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
export EMBEDDING_PROVIDER=openai-compatible
export EMBEDDING_API_KEY=your-key
export EMBEDDING_BASE_URL=https://api.openai.com/v1
export EMBEDDING_MODEL=text-embedding-3-small
export RAG_INDEX_DIR=/home/work/workproject2/project/rag/index
export MCP_SERVER_COMMAND=/root/anaconda3/envs/agent-learning/bin/python
export MCP_SERVER_ARGS="-m mcp_server.simulation_server"
```

未配置 `EMBEDDING_API_KEY` 时，系统会使用本地确定性向量 fallback，便于离线测试。

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

## 当前完成度

已完成：

- 后端项目骨架与分层结构
- 领域模型、订单类型、认证类型、队列状态、设备状态
- SQLite 持久化模型与基础仓储
- 订单创建、查询、修改、取消接口
- 检测设备仿真与认证项目仿真流程
- 队列排序、队列重建、阻塞识别
- RAG 索引重建、保存、加载和检索
- MCP stdio 独立服务入口与本地 fallback
- 排程批次和步骤持久化
- Jinja2 管理页：仪表盘、订单、队列、知识库、Agent轨迹
- LangGraph 多 Agent 编排
- FastAPI 接口与自动化测试

当前限制：

- FAISS 在当前环境未安装时会自动使用 numpy fallback；安装 `faiss-cpu` 后可切换为 FAISS 后端。
- MCP 独立服务目前封装的是仿真工具，还未接入真实实验室系统。
- 前端管理页以服务端渲染和少量原生 JS 为主，尚未加入权限控制和复杂交互组件。
- 设备状态、检测时间、检测项目仍是仿真种子数据。
- 尚未接入真实 LIMS、设备台账、检测标准库或历史工时数据。

## 后续步骤

1. 接入真实 embedding 服务，扩充认证标准、检测规则和历史订单知识库。
2. 将 MCP 工具替换为真实设备台账、LIMS、检测标准库和工时服务。
3. 增加订单执行状态流转、设备预约甘特图和异常事件闭环。
4. 增加用户、角色、权限和操作审计。
5. 将前端管理页增强为更完整的实验室队列运营工作台。

