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
- RAG：本地知识库 + 轻量检索 fallback，`faiss-cpu` 作为依赖目标保留
- 工具接入：MCP 模拟工具服务 + 本地工具客户端
- 测试：pytest
- 运行环境：WSL2 Conda 环境 `agent-learning`

## 系统架构

```text
API Layer
  ├─ /api/orders       订单增删改查
  ├─ /api/queue        队列查询与重建
  ├─ /api/monitor      队列与设备监测快照
  ├─ /api/knowledge    RAG 知识检索
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
  ├─ SimulationService  设备与检测项目仿真
  ├─ QueueService       优先级排序与排程
  └─ ToolClient         MCP 兼容工具调用门面

DB Layer
  ├─ orders
  ├─ equipment
  ├─ detection_projects
  └─ queue_events
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
├── rag/                 # RAG 检索与知识库
├── services/            # 仿真、调度和工具服务
├── tests/               # pytest 测试
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

- Swagger：`http://127.0.0.1:8002/docs`
- ReDoc：`http://127.0.0.1:8002/redoc`

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

重建队列：

```bash
curl -X POST http://127.0.0.1:8002/api/queue/rebuild
```

查询监测快照：

```bash
curl http://127.0.0.1:8002/api/monitor/snapshot
```

RAG 检索：

```bash
curl -X POST http://127.0.0.1:8002/api/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"query": "CCC 强制性认证 安全检测", "top_k": 3}'
```

运行 Agent：

```bash
curl -X POST http://127.0.0.1:8002/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task_type": "query_queue", "payload": {}}'
```

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
- RAG 检索命中
- MCP 本地工具接口结构
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
- 本地知识库检索
- MCP 模拟工具服务入口
- LangGraph 多 Agent 编排
- FastAPI 接口与自动化测试

当前限制：

- RAG 当前使用轻量本地检索 fallback，尚未接入正式 FAISS 或向量数据库索引。
- MCP 已提供模拟 server 和本地工具客户端，但还不是独立部署的远程工具服务闭环。
- 队列调度结果保存在内存快照中，尚未持久化为正式排程表。
- 设备状态、检测时间、检测项目仍是仿真种子数据。
- 暂无前端管理页面、权限控制、真实 LIMS/设备系统接入。

## 后续步骤

1. 将 RAG 替换为 FAISS 或向量数据库正式索引，并增加知识库更新接口。
2. 将 MCP Server 独立运行，Agent 通过 MCP client 调用真实工具服务。
3. 持久化排程结果，增加设备占用时间线、订单状态流转和异常事件表。
4. 增加前端管理页面，用于订单管理、队列监测、设备状态和 Agent 执行轨迹展示。
5. 接入真实设备台账、检测标准库、实验室 LIMS 系统或历史工时数据。

