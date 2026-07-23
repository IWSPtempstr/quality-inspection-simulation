import { showcaseOrders } from "@/showcase/data";

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
  if (["/events", "/notifications", "/schedule-previews", "/audit-logs"].includes(pathname)) return page([]) as T;
  if (["/resources/equipment", "/resources/employees", "/resources/shifts", "/resources/unavailability"].includes(pathname)) return [] as T;
  if (pathname === "/schedules/current") return { version: 1, steps: [] } as T;
  if (pathname === "/system/health") return { status: "healthy", services: { api: "healthy", scheduler: "healthy", messaging: "healthy" } } as T;
  throw new ShowcaseRequestError("showcase_data_unavailable");
}
