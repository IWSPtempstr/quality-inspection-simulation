# 电器产品检测排程管理系统

面向电器产品质量检测中心的订单、资源和排程管理系统。系统围绕检测订单接收、检测项目拆解、设备与人员约束、排程生成、执行回写、异常事件处理、通知提醒和操作审计，提供一套可运行的后端服务与轻量管理后台。

当前代码以可落地的业务闭环为主：核心写操作均通过确定性 API 和权限校验完成；智能能力只用于草稿、推荐、解释和文案辅助，不直接创建订单、修改排程或占用资源。

## 核心能力

- **订单管理**：创建、查询、修改、取消检测订单，支持普通、加急、VIP 订单和复检订单。
- **检测路线**：按认证类型生成默认检测流程，也支持订单级检测路线。
- **资源排程**：结合设备实例、人员班次、维护窗口、前处理、跨实验室转运、耗材配额和 SLA 生成排程。
- **策略比较**：支持多种候选排程策略评分，默认以 `sla_guarded_hybrid` 进行步骤级调度。
- **执行回写**：检测步骤可标记为运行中和完成；运行中步骤会锁定，后续重排不会打断。
- **事件闭环**：订单变化、设备故障、人员不可用、耗材不足、检测完成等事件进入事件中心，可触发排程心跳和闭环处理。
- **通知提醒**：生成设备空闲、检测完成、前处理、转运、SLA 风险、人员阻塞等通知，支持 SSE 实时推送。
- **权限与审计**：提供 `admin/scheduler/operator/viewer` 角色模拟，关键写操作进入审计日志。
- **业务辅助**：自然语言订单草稿、检测项目推荐、排程解释和异常处理建议均需要人工确认后才能进入确定性业务流程。

## 管理后台

启动后访问 `http://127.0.0.1:8002/`。

当前后台页面：

- `/`：检测队列仪表盘
- `/orders`：订单管理，含自然语言草稿和检测项目推荐
- `/queue`：队列与排程，含策略对比、甘特图和阻塞原因
- `/execution`：执行看板，支持开始/完成检测步骤
- `/events`：事件中心，支持事件筛选、处理建议、事件闭环和排程心跳
- `/notifications`：员工通知和仿真提醒
- `/audit`：操作审计日志

后台采用 Jinja2 服务端渲染和原生 JavaScript，不需要 Node、Vue 或 React 构建链。

## 技术栈

- FastAPI
- SQLite + SQLAlchemy
- Pydantic
- Jinja2 + 原生 JavaScript
- OR-Tools CP-SAT（滚动窗口候选排程）
- FAISS / numpy fallback（知识检索索引）
- pytest

可选能力：

- OpenAI 兼容 Chat API：用于异常解释、订单草稿、项目推荐和通知文案增强。
- OpenAI 兼容 Embedding API：用于知识库向量索引；未配置时使用本地确定性 fallback。
- MCP 仿真工具入口：用于开发和工具链验证，生产接入真实系统时应替换为明确的外部服务适配器。

## 系统结构

```text
project/
├── api/          # FastAPI 路由
├── agents/       # 业务辅助 Agent 编排
├── config/       # 环境配置
├── db/           # SQLAlchemy 模型与仓储
├── domain/       # Pydantic schema 与枚举
├── services/     # 排程、事件、通知、审计、监控等服务
├── rag/          # 知识库检索与索引
├── web/          # Jinja2 管理后台
├── tests/        # pytest 测试
├── data/         # SQLite、合成验证数据和评测样例
├── app.py        # FastAPI 应用入口
└── requirements.txt
```

## 主要接口

| 模块 | 接口 |
| --- | --- |
| 订单 | `POST /api/orders`, `GET /api/orders`, `PATCH /api/orders/{id}`, `DELETE /api/orders/{id}`, `POST /api/orders/{id}/retest` |
| 队列排程 | `GET /api/queue`, `POST /api/queue/rebuild`, `GET /api/schedules`, `GET /api/schedules/{run_id}/gantt` |
| 执行回写 | `PATCH /api/schedules/steps/{step_id}/running`, `PATCH /api/schedules/steps/{step_id}/complete` |
| 事件 | `GET /api/scheduling/events`, `POST /api/scheduling/events`, `PATCH /api/scheduling/events/{event_id}/resolve`, `POST /api/scheduling/heartbeat` |
| 通知 | `GET /api/notifications`, `PATCH /api/notifications/{id}/read`, `GET /api/notifications/stream` |
| 监控审计 | `GET /api/monitor/report`, `GET /api/admin/audit-logs`, `GET /api/admin/users` |
| 业务辅助 | `POST /api/agent/run` |

业务辅助任务包括：

- `draft_order_from_text`：生成订单草稿，不创建订单。
- `identify_projects`：推荐检测项目，保留确定性必检规则。
- `explain_schedule`：解释当前排程，不修改排程。
- `analyze_exception`：分析异常和阻塞，不关闭事件。
- `generate_notifications`：增强通知文案，不改变通知触发条件。
- `route_user_query`：返回建议任务，不自动执行任务。

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

复制环境变量文件：

```bash
cp .env.example .env
```

启动服务：

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m uvicorn app:create_app --factory --reload --port 8002
```

访问：

- 管理后台：`http://127.0.0.1:8002/`
- Swagger：`http://127.0.0.1:8002/docs`
- ReDoc：`http://127.0.0.1:8002/redoc`

## 运行模式

默认配置偏生产落地，只启用核心业务路由和管理后台。演示、数据集回放、MCP 仿真和离线评测属于开发/验证能力，可按需开启。

```bash
export APP_PROFILE=production
export ENABLE_WEB_UI=true
```

开发演示模式：

```bash
export APP_PROFILE=demo
```

`demo` 模式默认开启：

- 数据集回放接口 `/api/datasets`
- 仿真时钟接口 `/api/simulation`
- MCP 仿真状态接口 `/api/mcp`
- 离线评测入口 `/api/evaluation/offline/run`

常用配置：

```bash
export DATABASE_URL=sqlite:////home/work/workproject2/project/data/simulation.db
export SCHEDULER_HEARTBEAT_ENABLED=true
export SCHEDULER_HEARTBEAT_INTERVAL_SECONDS=30
export SCHEDULER_DEBOUNCE_SECONDS=30
export SCHEDULER_IMMEDIATE_SEVERITIES=critical,high
export SCHEDULER_DEFAULT_STRATEGY=sla_guarded_hybrid
export CP_SAT_TIME_LIMIT_SECONDS=10
export CP_SAT_ROLLING_HORIZON_DAYS=7
export CP_SAT_NUM_WORKERS=4
export CP_SAT_MAX_ACTIVE_ORDERS=80
```

可选 LLM / Embedding 配置：

```bash
export LLM_PROVIDER=openai-compatible
export LLM_API_KEY=your-chat-key
export LLM_BASE_URL=https://api.example.com/v1
export LLM_MODEL=qwen-plus
export LLM_ENABLE_THINKING=false

export EMBEDDING_PROVIDER=openai-compatible
export EMBEDDING_API_KEY=your-embedding-key
export EMBEDDING_BASE_URL=https://api.example.com/v1
export EMBEDDING_MODEL=text-embedding-v3
```

未配置 API Key 时，系统会使用确定性 fallback，业务接口仍可运行。

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

查询队列：

```bash
curl http://127.0.0.1:8002/api/queue
```

写入突发事件：

```bash
curl -X POST http://127.0.0.1:8002/api/scheduling/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "equipment_fault",
    "severity": "high",
    "entity_type": "equipment",
    "entity_id": "ENV-03",
    "payload": {"reason": "设备故障"}
  }'
```

触发排程心跳：

```bash
curl -X POST http://127.0.0.1:8002/api/scheduling/heartbeat
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

生成订单草稿：

```bash
curl -X POST http://127.0.0.1:8002/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "draft_order_from_text",
    "payload": {"user_text": "客户送检一批加急电磁兼容样品，希望三天内完成"}
  }'
```

查询审计日志：

```bash
curl http://127.0.0.1:8002/api/admin/audit-logs
```

## 测试

运行全量测试：

```bash
cd /home/work/workproject2/project
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest -q
```

常用定向测试：

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest tests/test_api_and_agents.py -q
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest tests/test_queue_service.py -q
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python -m pytest tests/test_mcp_and_web.py -q
```

## 数据说明

仓库内 `data/` 目录包含用于开发验证的合成数据集和评测样例。它们只用于机制验证、压力测试和演示，不代表任何真实检测中心的设备数量、检测耗时、人员排班、订单到达分布或插队规则。

真实落地时应接入：

- LIMS / 订单系统
- 设备台账和设备状态服务
- 检测项目标准库
- 人员排班、考勤和技能矩阵
- 历史工时与实际检测结果

## 当前限制

- 当前排程以规则调度、候选策略评分和滚动窗口优化组合为主，不声明全局数学最优。
- CP-SAT 作为窗口内候选策略，不适合对超大订单量进行全量一次性精排。
- MCP 目前是仿真工具入口，未接入真实设备或 LIMS。
- 权限模型为 header 模拟角色，未接入真实登录态和组织权限体系。
- 合成数据和 fallback 能保证本地运行，但不能替代真实生产数据校准。
- 智能能力只做辅助输入和解释，所有业务写操作仍由确定性 API 执行。

## 后续落地方向

1. 接入真实订单、设备、人员和检测标准数据源。
2. 将 header 角色替换为正式登录、组织权限和操作审批。
3. 基于真实工时数据校准检测耗时、人员配置和排程目标函数。
4. 补充暂停、返工、复核、报告签发等检测执行闭环。
5. 增加生产级监控、告警和审计导出。
