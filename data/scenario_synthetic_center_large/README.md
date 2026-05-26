# 合成拟真检测中心数据集

该目录为合成仿真数据集，用于多Agent检测队列系统的机制验证、压力测试和项目展示；其中设备数量、检测耗时、批处理容量、订单分布和优先级规则均为拟真假设，不代表某真实检测中心事实。

## 基本参数

- 随机种子：`20260522`
- 仿真周期：`2026-06-01` 至 `2026-11-30`
- 目标订单量：`5000`
- 订单类型分布：普通 75%，加急 18%，VIP 7%
- 认证类型分布：CCC 45%，CVC 35%，international 20%

## 文件说明

- `equipment_catalog.json`：设备类型、设备数量 d、设备实例、单台批处理容量 n。
- `project_catalog.json`：认证流程、检测步骤、设备需求、耗时分布 t、实验室区域、人员需求、准备时间和耗材需求。
- `order_arrivals.json`：合成订单到达记录；每个订单包含 `detection_route`、`preprocessing_profile` 和转运需求，用于表达订单级检测路线、共享设备类型和按 `t_min/t_mode/t_max` 抽样得到的步骤耗时。
- `order_lifecycle_events.json`：取消、修改、检测失败和重测创建事件，用于验证订单生命周期变化对重排的影响。
- `priority_rules.json`：非抢占式 VIP/加急优先规则。
- `operations_constraints.json`：班次、员工实例、前处理资源、转运资源、耗材日配额、维护和模拟故障。
- `knowledge_base/`：用于 RAG 检索的拟真知识文本。

## 生成与验证

```bash
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/generate_synthetic_center_dataset.py
/root/anaconda3/bin/conda run --no-capture-output -n agent-learning python scripts/validate_synthetic_center_dataset.py
```
