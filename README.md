# 电器产品检测排程工作台

电器产品检测排程工作台面向检测中心的订单、资源、排程、执行和运营协同。它将检测订单、设备与人员资源、正式排程版本、异常事件、通知和审计记录纳入同一套中心级业务边界，并通过审批后的排程写回连接伙伴系统。

系统采用浏览器单页应用与服务端 BFF 会话模式。所有业务写入均经由权限、版本和幂等校验；智能服务只提供检索、解释、诊断和文案辅助，不直接创建订单、确定排程或变更资源。

## 功能概览

- **订单与复测**：管理检测订单、所选检测项目、暂停与恢复、部分复测及其完整状态流转。
- **资源管理**：统一展示设备、员工、班次和不可用时段；资源事件按中心、实体与版本有序处理。
- **排程预览与审批**：创建不可变输入快照，接收候选结果，支持人工审核、批准或驳回；获批版本通过条件写回同步给伙伴系统。
- **执行与事件**：跟踪正式排程步骤的开始、完成与取消，管理系统事件的确认、关闭及处置记录。
- **通知与审计**：按订单创建人和同中心调度员生成通知，支持站内与 Webhook 通道；关键动作保留可追溯审计记录。
- **知识与辅助**：提供受控的知识检索、排程解释、异常诊断、通知草稿和审计筛选建议，并保留引用与人工确认边界。
- **运行健康**：汇总应用、数据、消息、缓存、伙伴写回和通知通道状态，输出可供运维处理的组件级健康信息。

## 系统架构

```text
React Web 应用
        |
        | 同源 /api/v1，OIDC/BFF 会话与 CSRF
        v
Go API 与 Worker
   |            |--------------------> Python 调度服务
   |            |                         |
   |            |<---- 候选结果回调 --------|
   |
   +--> PostgreSQL 16    业务数据、审计、Inbox、Outbox、排程版本
   +--> RabbitMQ 4       资源事件、通知投递、重试和死信队列
   +--> Redis 7          BFF 会话、CSRF、审批锁与重建去抖
   +--> Python 智能服务 --> Chroma  知识检索、解释与诊断
   +--> 伙伴系统         已审批排程的条件写回
```

排程从中心范围内的订单、资源、当前正式版本和冻结步骤创建快照。调度服务提交候选结果后，调度员或管理员进行审核；只有批准并完成伙伴条件写回的候选才会形成新的正式排程版本。资源事件、通知与外部写回通过 Inbox/Outbox 事务边界处理，消息投递使用确认、重试和死信队列保护。

## 角色与工作台

身份由 OIDC 提供方验证，Go API 根据中心声明与角色声明授权。浏览器只保存不透明会话标识，访问令牌和刷新令牌不会暴露给前端。

| 角色 | 主要职责 |
| --- | --- |
| `admin` | 管理中心级配置、资源、事件处置、审计与排程审批。 |
| `scheduler` | 创建和审核排程预览，处理资源影响、事件和正式排程。 |
| `operator` | 查看授权范围内的订单与排程，并登记检测步骤执行状态。 |
| `viewer` | 查看授权范围内的订单、资源、排程、事件和通知。 |

前端工作台覆盖订单、资源、排程预览、执行、事件、通知、知识查询、审计和系统健康。写操作携带幂等键、版本条件和会话绑定的 CSRF 值；冲突响应用于提示用户刷新并基于最新版本继续处理。

## 快速开始

### 前置条件

- Docker Engine 与 Docker Compose v2
- Node.js 22 和 npm（前端开发与验证）
- Go 1.26.3（Go 服务开发与验证）
- Python 3.12（调度和智能服务开发与验证）

### 启动本地服务栈

在仓库根目录执行：

```bash
docker compose -f deploy/compose/compose.yaml up --build
```

该命令启动 Go API/Worker、Python 调度与智能服务、PostgreSQL、RabbitMQ、Redis、Chroma 以及边缘代理。边缘健康检查地址为 `http://127.0.0.1:8080/healthz`，API 前缀为 `/api/v1`。

### 启动前端开发服务

```bash
cd apps/web
npm ci
npm run dev
```

前端采用 Vite 开发服务器。部署构建使用同源 `/api/v1`；将前端开发服务接入指定 API 时，设置 `VITE_API_BASE_URL` 为该 API 的 `/api/v1` 地址后再启动。

## Docker Compose

开发和受控端到端环境使用：

```bash
docker compose -f deploy/compose/compose.yaml up --build
```

生产环境使用独立的 Compose 文件。先执行显式数据库迁移，再启动完整服务栈：

```bash
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile migration run --rm migrate

docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml up --build -d --wait
```

生产镜像由 Nginx 提供 React 静态资源和 SPA 回退，并将 `/api/` 代理至 Go API。数据库、消息队列、缓存、知识存储和内部服务只在私有 Docker 网络中通信。

服务器目录、环境文件、Docker secret 文件、TLS 证书申请、备份恢复与回滚步骤见 [部署运行手册](deploy/compose/README.md)。请勿将密钥写入仓库、Compose 字面量或前端环境变量。

## 配置说明

生产环境以 `/etc/detection-center/compose.env` 为 Compose 配置入口，以根权限管理的 Docker secret 文件保存敏感值。可从 [`deploy/compose/env/`](deploy/compose/env/) 中的示例文件建立服务环境文件。

| 配置类别 | 用途 |
| --- | --- |
| OIDC | 配置发行方、客户端、回调地址、允许 scope、中心声明和角色声明。 |
| 会话与内部服务 | 配置会话有效期、服务间认证令牌和调度回调令牌。 |
| 数据与消息 | 配置 PostgreSQL、RabbitMQ、Redis 与 Chroma 的内部连接及持久化目录。 |
| 外部交付 | 配置伙伴排程条件写回地址/凭据和通知通道地址/凭据。 |
| 边缘与证书 | 配置公开域名、证书联系邮箱、ACME Web 根目录和证书目录。 |

生产启动会校验外部地址、必填密钥和服务配置。OIDC 回调地址应注册为 `https://<域名>/api/v1/auth/callback`，身份提供方需提供中心与角色声明。

## 开发与验证

前端命令均在 `apps/web` 目录执行：

```bash
npm run dev
npm run build
npm run lint
npm run typecheck
npm run test
npm run test:watch
npm run test:e2e
```

Go 服务验证命令在 `services/api-go` 目录执行：

```bash
go test -count=1 ./...
go vet ./...
go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.12.2 run
```

Python 服务的依赖和测试入口分别定义在 [`services/scheduler-py/pyproject.toml`](services/scheduler-py/pyproject.toml) 与 [`services/ai-py/pyproject.toml`](services/ai-py/pyproject.toml)。接口契约变更应先更新 OpenAPI 文件，再生成和验证相应服务边界。

## 项目结构

```text
apps/web/                 React 19 前端与浏览器测试
services/api-go/          Go API、消息 Worker、迁移、业务服务与集成测试
services/scheduler-py/    Python 排程服务、候选回调与调度评测
services/ai-py/           Python 智能服务、知识检索、诊断与辅助能力
contracts/openapi/        公共 API、调度内部 API 与智能服务内部 API 契约
deploy/                   Docker Compose、Nginx、监控、备份和恢复脚本
docs/                     部署、迁移、产品验收和运行文档
data/                     导入、验证、评测与知识材料
```

## 文档与契约

- [公共 API 契约](contracts/openapi/public-v1.yaml)：浏览器与 Go API 的 `/api/v1` 接口定义。
- [调度内部契约](contracts/openapi/scheduler-internal.yaml)：不可变快照、候选结果回调和调度服务接口定义。
- [智能服务内部契约](contracts/openapi/ai-internal.yaml)：知识检索、解释、诊断和辅助接口定义。
- [部署运行手册](deploy/compose/README.md)：服务器准备、迁移、TLS、监控、备份、恢复和回滚。
- [数据导入与核对文档](docs/migration/README.md)：导入范围、字段边界、核对和回滚流程。
- [前端验收指引](docs/product/frontend-gate.md)：前端构建、测试与浏览器验收记录。
- [开发规格](DEV_SPEC.md)：领域边界、服务契约、交付阶段和验证要求。
