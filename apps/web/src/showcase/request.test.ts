import { afterEach, describe, expect, it, vi } from "vitest";
import { ShowcaseRequestError, showcaseRequest } from "@/showcase/request";

describe("showcaseRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns reviewed in-bundle view data without issuing a network request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const orders = await showcaseRequest<{ items: Array<{ id: string }> }>("/orders");

    expect(orders.items.length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"])("rejects %s before it can mutate a showcased workbench", async (method) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(showcaseRequest("/orders", { method, body: "{}" })).rejects.toEqual(
      expect.objectContaining<Partial<ShowcaseRequestError>>({ code: "showcase_mutation_unavailable" }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects paths without a reviewed static response instead of falling back to fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(showcaseRequest("/not-a-showcase-endpoint")).rejects.toEqual(
      expect.objectContaining<Partial<ShowcaseRequestError>>({ code: "showcase_data_unavailable" }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
