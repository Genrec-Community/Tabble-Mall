import { afterEach, describe, expect, it, vi } from "vitest";
import { loadMall } from "@/lib/server-api";

const mall = { name: "Phoenix Pune", slug: "phoenix-pune", city: "Pune", stores: [{ name: "Burger Hub", slug: "burger-hub", description: null }] };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("loadMall", () => {
  it("fetches the mall from the internal API address, cached for a minute and tagged by slug", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const fetchMock = vi.fn().mockResolvedValue(json(200, mall));
    vi.stubGlobal("fetch", fetchMock);

    const result = await loadMall("phoenix-pune");

    expect(result).toEqual(mall);
    const [request, init] = fetchMock.mock.calls[0] as [Request, { next?: { revalidate: number; tags: string[] } }];
    expect(request.url).toBe("http://api:8000/api/v1/public/malls/phoenix-pune");
    expect(init.next).toEqual({ revalidate: 60, tags: ["mall:phoenix-pune"] });
  });

  it("returns null for a mall that does not exist or is suspended", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(404, { code: "not_found", status: 404 })));
    expect(await loadMall("nope")).toBeNull();
  });

  it("surfaces real failures instead of pretending the mall is missing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(500, { code: "internal_error", status: 500 })));
    await expect(loadMall("phoenix-pune")).rejects.toThrow();
  });
});
