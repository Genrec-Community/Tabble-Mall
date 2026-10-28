import { afterEach, describe, expect, it, vi } from "vitest";
import { healthGetHealth } from "@/lib/api";
import { configureApiClient } from "@/lib/api-config";

const ok = () =>
  new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

afterEach(() => vi.unstubAllGlobals());

describe("configureApiClient", () => {
  it("sends the bearer token, CSRF header and credentials on every call", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok());
    vi.stubGlobal("fetch", fetchMock);
    configureApiClient({
      baseUrl: "http://test",
      getAccessToken: () => "tok",
      onUnauthorized: vi.fn(),
    });

    await healthGetHealth();

    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.url).toBe("http://test/api/v1/health");
    expect(req.headers.get("authorization")).toBe("Bearer tok");
    expect(req.headers.get("x-requested-with")).toBe("mallt");
    expect(req.credentials).toBe("include");
  });

  it("omits Authorization when there is no token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok());
    vi.stubGlobal("fetch", fetchMock);
    configureApiClient({ baseUrl: "http://test", getAccessToken: () => null, onUnauthorized: vi.fn() });

    await healthGetHealth();

    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.headers.get("authorization")).toBeNull();
  });
});
