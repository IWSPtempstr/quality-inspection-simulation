# Phase 5 I2 一次性脱敏数据导入总 runbook

本目录定义生产重建切换前的“一次性脱敏数据导入、对账与回滚”操作规范。
它是 Phase 5 I2 的执行边界，不创建新的运行时代码，也不授权应用在启动时
自动导入、自动修表或绕过 Goose / 审批 / Inbox / Outbox 规则。

## 目标

在不破坏 `DEV_SPEC.md` 的系统边界前提下，将中心的脱敏业务语料一次性导入到
新系统的 PostgreSQL / Chroma / BM25 重建流程所需的权威存储中，并留下可审计
的导入证据、对账结果和可执行回滚路径。

## 适用范围

I2 只覆盖以下一次性导入对象：

- 历史订单与其项目事实
- 设备、员工、技能、班次、停用/不可用事实
- 标准文档版本、块元数据与激活版本
- 历史异常/事件的脱敏事实，仅用于事件处理和后续人工评审，不自动成为长期记忆

I2 不做以下事情：

- 不开放任何 UI 或 API 的历史回放
- 不直接导入正式排程、审批状态或伙伴写回结果作为新系统权威真相
- 不把历史 incident 自动写成 `resolved_exception_cases` 的 approved 长期记忆
- 不跳过 Goose migration、OIDC、Inbox/Outbox、版本检查或人工审批

## 文档组成

主入口与详细执行文档：

- [i2-runbook.md](</home/work/workproject2/project/docs/migration/i2-runbook.md>)
  - I2 的完整执行手册，覆盖导入前检查、导入顺序、对账门槛、失败处理与回滚触发
- [import-manifest.template.yaml](</home/work/workproject2/project/docs/migration/import-manifest.template.yaml>)
  - 每次正式导入前复制并填写的声明清单
- [field-scope-matrix.md](</home/work/workproject2/project/docs/migration/field-scope-matrix.md>)
  - 导入对象、字段范围、明确排除项与 Chroma/BM25 重建边界
- [reconciliation-checklist.md](</home/work/workproject2/project/docs/migration/reconciliation-checklist.md>)
  - 导入后对账步骤与通过门槛
- [rollback-plan.md](</home/work/workproject2/project/docs/migration/rollback-plan.md>)
  - 标准化回滚触发条件、回滚顺序与完成条件
- [evidence-template.md](</home/work/workproject2/project/docs/migration/evidence-template.md>)
  - 本次导入的执行记录模板

兼容性的简版中文说明：

- [import-field-boundary.md](</home/work/workproject2/project/docs/migration/import-field-boundary.md>)
  - 字段边界与脱敏要求的简版说明，便于业务 reviewer 快速核对
- [rollback-runbook.md](</home/work/workproject2/project/docs/migration/rollback-runbook.md>)
  - 回滚流程的简版中文说明，便于窗口内快速查阅

## 执行顺序

1. 复制并填写 manifest
2. 按字段边界准备脱敏输入
3. 完成导入前检查
4. 执行一次性导入
5. 完成 PostgreSQL / Chroma / BM25 / 业务抽样对账
6. 记录证据并由负责人签字
7. 若任何关键门槛失败，立即按回滚 runbook 回退

## 成功定义

I2 仅在以下条件全部满足时算完成：

- 所有输入文件、批次、哈希、行数、负责人与窗口都有记录
- PostgreSQL 权威表计数与抽样关系通过
- Chroma / BM25 只包含可重建检索数据，且激活版本与 PostgreSQL 记录一致
- 未经人工评审的 incident 没有变成可检索长期记忆
- 回滚步骤在文档上可执行，且回滚触发条件明确
