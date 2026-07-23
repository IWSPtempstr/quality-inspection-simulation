import type { AuditLog, Employee, Equipment, Event, Health, Notification, Order, Schedule, SchedulePreview, Shift, Unavailability } from "@/api/types";

// Deliberately in-bundle, desensitized data. The public Pages build never imports MSW fixtures.
export const showcaseOrders: Order[] = [
  {
    id: "ORD-20260714-001",
    sample_name: "空气炸锅 A8",
    sample_quantity: 3,
    certification_type: "CCC",
    priority: "vip",
    project_ids: ["safety", "emc"],
    status: "scheduled",
    version: 4,
    created_at: "2026-07-14T09:00:00+08:00",
    promised_finish_time: "2026-07-16T17:00:00+08:00",
  },
  {
    id: "ORD-20260714-002",
    sample_name: "电热水壶 K2",
    sample_quantity: 2,
    certification_type: "CVC",
    priority: "urgent",
    project_ids: ["safety"],
    status: "blocked",
    version: 2,
    created_at: "2026-07-14T10:30:00+08:00",
    promised_finish_time: "2026-07-15T17:00:00+08:00",
  },
  {
    id: "ORD-20260714-003",
    sample_name: "扫地机器人 S3",
    sample_quantity: 1,
    certification_type: "CCC",
    priority: "normal",
    project_ids: ["emc", "environment"],
    status: "pending",
    version: 1,
    created_at: "2026-07-14T11:10:00+08:00",
    promised_finish_time: "2026-07-18T17:00:00+08:00",
  },
];

export const showcaseEquipment: Equipment[] = [
  { id: "EQ-EMC-03", name: "EMC 暗室 03", status: "running", capacity: 1, project_ids: ["emc"], version: 12 },
  { id: "EQ-SAFE-02", name: "安全测试台 02", status: "available", capacity: 2, project_ids: ["safety"], version: 8 },
  { id: "EQ-ENV-01", name: "环境箱 01", status: "maintenance", capacity: 1, project_ids: ["environment"], version: 6 },
];

export const showcaseEmployees: Employee[] = [
  { id: "EMP-014", name: "陈工", skills: ["safety", "emc"], shift_id: "SHIFT-DAY", version: 7 },
  { id: "EMP-021", name: "林工", skills: ["environment", "safety"], shift_id: "SHIFT-DAY", version: 5 },
  { id: "EMP-032", name: "周工", skills: ["emc"], shift_id: "SHIFT-EVENING", version: 3 },
];

export const showcaseShifts: Shift[] = [
  { id: "SHIFT-DAY", name: "白班", start_time: "08:30", end_time: "17:30" },
  { id: "SHIFT-EVENING", name: "晚班", start_time: "13:00", end_time: "21:00" },
];

export const showcaseUnavailability: Unavailability[] = [
  { id: "UNAV-ENV-01", entity_id: "EQ-ENV-01", starts_at: "2026-07-15T08:00:00+08:00", ends_at: "2026-07-16T18:00:00+08:00", reason: "温控校准" },
  { id: "UNAV-EMP-032", entity_id: "EMP-032", starts_at: "2026-07-15T13:00:00+08:00", ends_at: "2026-07-15T17:30:00+08:00", reason: "技能复核" },
];

export const showcaseSchedule: Schedule = {
  version: 18,
  steps: [
    { id: "STEP-018-01", order_id: "ORD-20260714-001", project_id: "safety", equipment_id: "EQ-SAFE-02", employee_ids: ["EMP-014"], starts_at: "2026-07-15T09:00:00+08:00", ends_at: "2026-07-15T10:30:00+08:00", status: "completed", frozen: true, version: 3 },
    { id: "STEP-018-02", order_id: "ORD-20260714-001", project_id: "emc", equipment_id: "EQ-EMC-03", employee_ids: ["EMP-014", "EMP-032"], starts_at: "2026-07-15T10:45:00+08:00", ends_at: "2026-07-15T12:45:00+08:00", status: "running", frozen: true, version: 4 },
    { id: "STEP-018-03", order_id: "ORD-20260714-002", project_id: "safety", equipment_id: "EQ-SAFE-02", employee_ids: ["EMP-021"], starts_at: "2026-07-15T13:30:00+08:00", ends_at: "2026-07-15T15:00:00+08:00", status: "scheduled", frozen: false, version: 2 },
    { id: "STEP-018-04", order_id: "ORD-20260714-003", project_id: "emc", equipment_id: "EQ-EMC-03", employee_ids: ["EMP-032"], starts_at: "2026-07-15T15:15:00+08:00", ends_at: "2026-07-15T17:15:00+08:00", status: "scheduled", frozen: false, version: 1 },
  ],
};

export const showcasePreviews: SchedulePreview[] = [{
  id: "PREVIEW-20260715-01",
  status: "pending_review",
  algorithm_used: "cp_sat",
  solver_status: "OPTIMAL",
  base_schedule_version: 18,
  resource_snapshot_version: 26,
  frozen_step_count: 2,
  changed_step_count: 2,
  delayed_order_count: 1,
  weighted_delay_minutes: 45,
  total_delay_minutes: 90,
  blockers: [{ step_id: "STEP-018-03", order_id: "ORD-20260714-002", reason: "环境箱维护窗口占用环境可靠性后续步骤。" }],
  changes: [
    { step_id: "STEP-018-03", type: "moved", from: "2026-07-15T13:30:00+08:00", to: "2026-07-15T14:00:00+08:00" },
    { step_id: "STEP-018-04", type: "moved", from: "2026-07-15T15:15:00+08:00", to: "2026-07-15T16:15:00+08:00" },
  ],
  schedule: {
    version: 19,
    steps: showcaseSchedule.steps.map((step) => step.id === "STEP-018-03" ? { ...step, starts_at: "2026-07-15T14:00:00+08:00", ends_at: "2026-07-15T15:30:00+08:00" } : step.id === "STEP-018-04" ? { ...step, starts_at: "2026-07-15T16:15:00+08:00", ends_at: "2026-07-15T18:15:00+08:00" } : step),
  },
  version: 1,
  fallback_used: false,
  fallback_reason: null,
}];

export const showcaseEvents: Event[] = [
  {
    id: "EVT-20260715-01",
    event_type: "设备维护窗口冲突",
    status: "open",
    severity: "high",
    entity_id: "EQ-ENV-01",
    version: 2,
    occurred_at: "2026-07-15T08:12:00+08:00",
    payload: { resource: "环境箱 01", impact: "环境可靠性步骤需重新确认", reporter: "资源监控" },
  },
  {
    id: "EVT-20260715-02",
    event_type: "加急订单交期风险",
    status: "investigating",
    severity: "medium",
    entity_id: "ORD-20260714-002",
    version: 1,
    occurred_at: "2026-07-15T09:05:00+08:00",
    payload: { order: "ORD-20260714-002", promised_finish: "2026-07-15 17:00", cause: "资源窗口调整" },
  },
];

export const showcaseNotifications: Notification[] = [
  { id: "NOT-20260715-01", title: "环境箱 01 维护窗口影响候选排程", status: "unread", created_at: "2026-07-15T08:15:00+08:00" },
  { id: "NOT-20260715-02", title: "候选排程 PREVIEW-20260715-01 等待审核", status: "read", created_at: "2026-07-15T09:10:00+08:00" },
];

export const showcaseAuditLogs: AuditLog[] = [
  { id: "AUD-20260715-01", actor_id: "scheduler-014", action: "schedule_preview.created", created_at: "2026-07-15T09:08:00+08:00", detail: { preview_id: "PREVIEW-20260715-01", base_version: 18 } },
  { id: "AUD-20260715-02", actor_id: "system", action: "event.opened", created_at: "2026-07-15T08:12:00+08:00", detail: { event_id: "EVT-20260715-01", resource_id: "EQ-ENV-01" } },
  { id: "AUD-20260715-03", actor_id: "operator-021", action: "schedule_step.started", created_at: "2026-07-15T10:45:00+08:00", detail: { step_id: "STEP-018-02", schedule_version: 18 } },
];

export const showcaseHealth: Health = {
  status: "healthy",
  services: {
    api: "healthy",
    postgresql: "healthy",
    rabbitmq: "healthy",
    redis: "healthy",
    scheduler: "healthy",
    knowledge: "healthy",
  },
};
