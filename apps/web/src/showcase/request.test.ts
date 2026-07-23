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

  it("provides populated read-only data for every operational workbench surface", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const [equipment, employees, shifts, unavailable, schedule, previews, events, notifications, audit, health] = await Promise.all([
      showcaseRequest<Array<{ id: string }>>("/resources/equipment"),
      showcaseRequest<Array<{ id: string }>>("/resources/employees"),
      showcaseRequest<Array<{ id: string }>>("/resources/shifts"),
      showcaseRequest<Array<{ id: string }>>("/resources/unavailability"),
      showcaseRequest<{ steps: Array<{ id: string }> }>("/schedules/current"),
      showcaseRequest<{ items: Array<{ id: string }> }>("/schedule-previews"),
      showcaseRequest<{ items: Array<{ id: string }> }>("/events"),
      showcaseRequest<{ items: Array<{ id: string }> }>("/notifications"),
      showcaseRequest<{ items: Array<{ id: string }> }>("/audit-logs"),
      showcaseRequest<{ services: Record<string, string> }>("/system/health"),
    ]);

    expect(equipment).not.toHaveLength(0);
    expect(employees).not.toHaveLength(0);
    expect(shifts).not.toHaveLength(0);
    expect(unavailable).not.toHaveLength(0);
    expect(schedule.steps).not.toHaveLength(0);
    expect(previews.items).not.toHaveLength(0);
    expect(events.items).not.toHaveLength(0);
    expect(notifications.items).not.toHaveLength(0);
    expect(audit.items).not.toHaveLength(0);
    expect(Object.keys(health.services)).toHaveLength(6);
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
