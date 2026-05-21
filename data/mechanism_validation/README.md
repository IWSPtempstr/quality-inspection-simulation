# 最小机制验证数据集

该目录用于验证系统机制是否可闭环运行，不用于声明真实实验室设备参数或真实检测时长。

## 数据组合

- `orders.json`：4 个订单样本，覆盖 `vip`、`urgent`、`normal` 三类优先级，以及一个无法匹配检测项目的阻塞订单。
- `knowledge_base/`：4 份知识文本，覆盖 CCC、CVC、国际认证和设备约束，用于 RAG 重建索引与检索命中验证。

## 验证变量

- 优先级：`vip > urgent > normal`
- 认证流程：CCC、CVC、international 三类检测步骤
- 设备约束：设备类型、容量、检测时长、批次数
- 状态结果：scheduled 与 blocked
- 协同机制：Orchestrator、Queue Scheduler、Equipment Monitor 的 handoff 与 MCP 状态查询

## 执行命令

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/validate_system_mechanism.py
```
