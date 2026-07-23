export const showcaseOrders = [
  { id: "ORD-20260714-001", sample_name: "空气炸锅 A8", status: "已排程", promised_finish_time: "2026-07-16 17:00" },
  { id: "ORD-20260714-002", sample_name: "电热水壶 K2", status: "待排程", promised_finish_time: "2026-07-15 17:00" },
];

export const showcaseFacts = {
  resources: ["EMC 暗室 03：运行中", "安全测试台 02：可用", "环境箱 01：维护中"],
  scheduling: ["候选版本 13 等待审核", "1 个运行中步骤保持冻结", "1 个订单存在交期风险"],
  execution: ["STEP-001 安全测试：运行中", "STEP-002 EMC 测试：已排程"],
  events: ["环境箱 01 温控异常：待处理", "加急订单插入：已记录"],
  knowledge: ["环境试验规范 6.3：设备异常时停止相关项目并评估已排任务。"],
  notifications: ["环境箱 01 故障影响待处理订单", "候选排程等待审批"],
  audit: ["已记录候选排程创建操作", "已记录资源异常事件"],
  health: ["API：正常", "消息队列：正常", "知识服务：降级"],
} as const;
