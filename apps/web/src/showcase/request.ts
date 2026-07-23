import {
  showcaseAuditLogs,
  showcaseEmployees,
  showcaseEquipment,
  showcaseEvents,
  showcaseHealth,
  showcaseNotifications,
  showcaseOrders,
  showcasePreviews,
  showcaseSchedule,
  showcaseShifts,
  showcaseUnavailability,
} from "@/showcase/data";

export type ShowcaseRequestErrorCode = "showcase_mutation_unavailable" | "showcase_data_unavailable";

export class ShowcaseRequestError extends Error {
  constructor(public readonly code: ShowcaseRequestErrorCode) {
    super(code === "showcase_mutation_unavailable" ? "公开产品展示不提供业务写入。" : "公开产品展示没有该页面数据。");
  }
}

export async function showcaseRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) throw new ShowcaseRequestError("showcase_mutation_unavailable");
  const pathname = path.split("?", 1)[0];
  const page = (items: unknown[]) => ({ items, page: 1, page_size: 25, total: items.length });
  if (pathname === "/orders") return page(showcaseOrders) as T;
  if (pathname === "/events") return page(showcaseEvents) as T;
  if (pathname === "/notifications") return page(showcaseNotifications) as T;
  if (pathname === "/schedule-previews") return page(showcasePreviews) as T;
  if (pathname === "/audit-logs") return page(showcaseAuditLogs) as T;
  if (pathname === "/resources/equipment") return showcaseEquipment as T;
  if (pathname === "/resources/employees") return showcaseEmployees as T;
  if (pathname === "/resources/shifts") return showcaseShifts as T;
  if (pathname === "/resources/unavailability") return showcaseUnavailability as T;
  if (pathname === "/schedules/current") return showcaseSchedule as T;
  if (pathname === "/system/health") return showcaseHealth as T;
  if (pathname.startsWith("/events/")) {
    const event = showcaseEvents.find((item) => item.id === pathname.slice("/events/".length));
    if (event) return event as T;
  }
  throw new ShowcaseRequestError("showcase_data_unavailable");
}
