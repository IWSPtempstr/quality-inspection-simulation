import { http, HttpResponse, type JsonBodyType } from "msw";
import { mockAudit, mockAuditFilterSuggestion, mockCaseCandidate, mockDiagnosis, mockEmployees, mockEquipment, mockEvents, mockHealth, mockKnowledge, mockNotificationDraft, mockNotifications, mockOrders, mockPreflight, mockPreview, mockScheduleExplanation, mockSession, mockShifts, mockUnavailability } from "@/mocks/data";

const page = <T,>(items: T[]) => ({ items, page: 1, page_size: 25, total: items.length });
const problem = (status: number, title: string, detail: string) => HttpResponse.json({ type: "about:blank", title, status, detail }, { status, headers: { "Content-Type": "application/problem+json" } });
const api = "*/api/v1";
type IdempotencyResponse = { status: number; body?: JsonBodyType };
const idempotencyResponses = new Map<string, IdempotencyResponse>();

const idempotencyResponseKey = (request: Request) => {
  const key = request.headers.get("Idempotency-Key");
  return key ? `${request.method}:${new URL(request.url).pathname}:${key}` : undefined;
};
const replayIdempotent = (request: Request) => {
  const key = idempotencyResponseKey(request);
  const response = key ? idempotencyResponses.get(key) : undefined;
  return response ? response.body === undefined ? new HttpResponse(null, { status: response.status }) : HttpResponse.json(response.body, { status: response.status }) : undefined;
};
const idempotentJson = (request: Request, body: JsonBodyType, status = 200) => {
  const key = idempotencyResponseKey(request);
  if (key) idempotencyResponses.set(key, { body, status });
  return HttpResponse.json(body, { status });
};
const idempotentEmpty = (request: Request) => {
  const key = idempotencyResponseKey(request);
  if (key) idempotencyResponses.set(key, { status: 204 });
  return new HttpResponse(null, { status: 204 });
};

const g4ToG7FixtureHandlers = [
  http.get(`${api}/session/me`, () => HttpResponse.json(mockSession)),
  http.get(`${api}/orders`, ({ request }) => {
    const query = new URL(request.url).searchParams.get("q")?.trim().toLowerCase();
    const items = query ? mockOrders.filter((order) => [order.id, order.sample_name, order.status].some((value) => value.toLowerCase().includes(query))) : mockOrders;
    return HttpResponse.json(page(items));
  }),
  http.post(`${api}/orders`, async ({ request }) => {
    const replay = replayIdempotent(request);
    if (replay) return replay;
    const order = { id: `ORD-${String(mockOrders.length + 1).padStart(3, "0")}`, status: "pending", version: 1, created_at: new Date().toISOString(), ...(await request.json() as object) } as typeof mockOrders[number];
    mockOrders.unshift(order);
    return idempotentJson(request, order, 201);
  }),
  http.get(`${api}/orders/:id`, ({ params }) => HttpResponse.json(mockOrders.find((item) => item.id === params.id) ?? null)),
  http.patch(`${api}/orders/:id`, async ({ params, request }) => {
    const replay = replayIdempotent(request);
    if (replay) return replay;
    const order = mockOrders.find((item) => item.id === params.id);
    if (!order) return problem(404, "订单不存在", "未找到指定订单");
    if (request.headers.get("If-Match") === "stale" || request.headers.get("If-Match") !== String(order.version)) return problem(409, "版本冲突", "订单已被其他操作更新");
    const updated = { ...order, ...(await request.json() as object), version: order.version + 1 };
    Object.assign(order, updated);
    return idempotentJson(request, order);
  }),
  http.post(`${api}/orders/:id/retests`, async ({ params, request }) => {
    const replay = replayIdempotent(request);
    if (replay) return replay;
    const order = mockOrders.find((item) => item.id === params.id);
    if (!order) return problem(404, "订单不存在", "未找到指定订单");
    if (request.headers.get("If-Match") !== String(order.version)) return problem(409, "版本冲突", "订单已被其他操作更新");
    const { reason } = await request.json() as { reason?: string };
    if (!reason?.trim()) return problem(400, "复测原因不能为空", "请说明发起复测的原因");
    const retest = { ...order, id: `${order.id}-RETEST`, status: "pending", version: 1, created_at: new Date().toISOString() };
    mockOrders.unshift(retest);
    return idempotentJson(request, retest, 201);
  }),
  http.get(`${api}/resources/equipment`, () => HttpResponse.json(mockEquipment)),
  http.get(`${api}/resources/employees`, () => HttpResponse.json(mockEmployees)),
  http.get(`${api}/resources/shifts`, () => HttpResponse.json(mockShifts)),
  http.get(`${api}/resources/unavailability`, () => HttpResponse.json(mockUnavailability)),
  http.get(`${api}/schedules/current`, () => HttpResponse.json(mockPreview.schedule)),
  http.get(`${api}/schedule-previews`, () => HttpResponse.json(page([mockPreview]))),
  http.post(`${api}/schedule-previews`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, mockPreview, 202)),
  http.get(`${api}/schedule-previews/:id`, () => HttpResponse.json(mockPreview)),
  http.post(`${api}/schedule-previews/:id/approve`, ({ request }) => replayIdempotent(request) ?? (request.headers.get("If-Match") === "stale" ? problem(409, "版本冲突", "候选排程已被其他调度员处理") : idempotentJson(request, { ...mockPreview, status: "approved" }))),
  http.post(`${api}/schedule-previews/:id/reject`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { ...mockPreview, status: "rejected" })),
  http.patch(`${api}/schedule-steps/:id/start`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { ...mockPreview.schedule.steps[0], status: "running", frozen: true })),
  http.patch(`${api}/schedule-steps/:id/complete`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { ...mockPreview.schedule.steps[0], status: "completed", frozen: false })),
  http.get(`${api}/events`, () => HttpResponse.json(page(mockEvents))),
  http.get(`${api}/events/:id`, ({ params }) => HttpResponse.json(mockEvents.find((event) => event.id === params.id) ?? null)),
  http.post(`${api}/events/:id/close`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { ...mockEvents[0], status: "closed" })),
  http.get(`${api}/notifications`, () => HttpResponse.json(page(mockNotifications))),
  http.patch(`${api}/notifications/:id/read`, ({ request }) => replayIdempotent(request) ?? idempotentEmpty(request)),
  http.get(`${api}/system/health`, () => HttpResponse.json(mockHealth)),
];

const g8AssistanceFixtureHandlers = [
  http.post(`${api}/schedule-previews/:id/explanation`, () => HttpResponse.json(mockScheduleExplanation)),
  http.post(`${api}/schedule-previews/preflight`, () => HttpResponse.json(mockPreflight)),
  http.post(`${api}/events/:id/diagnose`, () => HttpResponse.json(mockDiagnosis, { status: 202 })),
  http.post(`${api}/events/:id/case-candidates`, () => HttpResponse.json(mockCaseCandidate)),
  http.post(`${api}/exception-case-candidates/:id/submit`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { id: "CASE-REVIEW-001", event_id: "EVT-001", status: "pending_review", version: 1, submitted_at: "2026-07-14T09:30:00+08:00" }, 201)),
  http.post(`${api}/notification-drafts`, () => HttpResponse.json(mockNotificationDraft)),
  http.post(`${api}/notification-drafts/:id/send`, ({ request }) => replayIdempotent(request) ?? idempotentJson(request, { id: "DELIVERY-001", draft_id: "draft-signed-not-01", status: "accepted", accepted_at: "2026-07-14T09:30:00+08:00" }, 202)),
  http.post(`${api}/audit-logs/filter-suggestions`, () => HttpResponse.json(mockAuditFilterSuggestion)),
];

const fixtureOnlyHandlers = [
  http.post(`${api}/knowledge/query`, () => HttpResponse.json(mockKnowledge)),
  http.post(`${api}/knowledge/impact-analysis`, () => HttpResponse.json(mockKnowledge)),
  http.get(`${api}/audit-logs`, () => HttpResponse.json(page(mockAudit))),
];

// Knowledge retrieval and the audit list remain fixture-backed until their own
// Go contracts are delivered. G8 assistance operations are mounted by Go;
// do not add them here. G4-G7 operations also remain outside this default set.
export const handlers = fixtureOnlyHandlers;

// The development-only manual demo must remain self-contained and must not
// call Go. Tests use these same fixed fixtures for feature-level coverage.
export const fixtureHandlers = [...g4ToG7FixtureHandlers, ...g8AssistanceFixtureHandlers, ...fixtureOnlyHandlers];
