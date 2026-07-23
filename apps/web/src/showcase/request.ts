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
  if (path === "/orders") return { items: showcaseOrders, page: 1, page_size: showcaseOrders.length, total: showcaseOrders.length } as T;
  throw new ShowcaseRequestError("showcase_data_unavailable");
}
