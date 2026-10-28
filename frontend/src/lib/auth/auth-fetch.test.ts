import { describe, expect, it, vi } from "vitest";
import { createAuthFetch, kindForUrl } from "@/lib/auth/auth-fetch";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const invalidToken = () => json(401, { code: "invalid_token", status: 401 });

function setup(responses: Response[], refresh: (kind: string) => Promise<string | null>) {
  const base = vi.fn();
  responses.forEach((r) => base.mockResolvedValueOnce(r));
  const onUnauthorized = vi.fn();
  const authFetch = createAuthFetch({ fetch: base as unknown as typeof fetch, refresh, onUnauthorized });
  return { base, onUnauthorized, authFetch };
}

const post = (url: string, token = "old") =>
  new Request(url, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ name: "Burger Hub" }),
  });

describe("kindForUrl", () => {
  it("routes customer endpoints to the customer session and everything else to staff", () => {
    expect(kindForUrl("http://x/api/v1/auth/customer/me")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/customer/orders")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/malls/phoenix/cart")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/malls/phoenix/cart/lines/abc")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/malls/phoenix/checkout")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/orders")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/orders?limit=20")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/orders/abc")).toBe("customer");
    expect(kindForUrl("http://x/api/v1/orders/stores/abc/cancel")).toBe("customer");
    // staff routes that merely contain "orders" or sit under /malls/
    expect(kindForUrl("http://x/api/v1/stores/abc/orders")).toBe("staff");
    expect(kindForUrl("http://x/api/v1/orgs/abc/orders")).toBe("staff");
    expect(kindForUrl("http://x/api/v1/malls/0192abcd-0000-7000-8000-000000000001/orders")).toBe("staff");
    expect(kindForUrl("http://x/api/v1/malls/0192abcd-0000-7000-8000-000000000001/stores")).toBe("staff");
    expect(kindForUrl("http://x/api/v1/auth/staff/me")).toBe("staff");
    expect(kindForUrl("http://x/api/v1/orgs")).toBe("staff");
  });
});

describe("createAuthFetch", () => {
  it("passes successful responses straight through", async () => {
    const { authFetch, base } = setup([json(200, { ok: true })], async () => "x");
    const r = await authFetch(post("http://x/api/v1/orgs"));
    expect(r.status).toBe(200);
    expect(base).toHaveBeenCalledTimes(1);
  });

  it("on an expired access token, refreshes once and retries with the new token and the same body", async () => {
    const refresh = vi.fn().mockResolvedValue("fresh");
    const { authFetch, base } = setup([invalidToken(), json(200, { ok: true })], refresh);

    const r = await authFetch(post("http://x/api/v1/orgs"));

    expect(r.status).toBe(200);
    expect(refresh).toHaveBeenCalledWith("staff");
    expect(base).toHaveBeenCalledTimes(2);
    const retry = base.mock.calls[1][0] as Request;
    expect(retry.headers.get("authorization")).toBe("Bearer fresh");
    expect(await retry.json()).toEqual({ name: "Burger Hub" });
  });

  it("uses the customer session for customer URLs", async () => {
    const refresh = vi.fn().mockResolvedValue("c-fresh");
    const { authFetch } = setup([invalidToken(), json(200, {})], refresh);
    await authFetch(post("http://x/api/v1/auth/customer/me"));
    expect(refresh).toHaveBeenCalledWith("customer");
  });

  it("when the refresh fails, reports sign-out and returns the original 401 without retrying", async () => {
    const { authFetch, base, onUnauthorized } = setup([invalidToken()], async () => null);
    const r = await authFetch(post("http://x/api/v1/orgs"));
    expect(r.status).toBe(401);
    expect(base).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledWith("staff");
  });

  it("never retries more than once", async () => {
    const { authFetch, base, onUnauthorized } = setup([invalidToken(), invalidToken()], async () => "fresh");
    const r = await authFetch(post("http://x/api/v1/orgs"));
    expect(r.status).toBe(401);
    expect(base).toHaveBeenCalledTimes(2);
    expect(onUnauthorized).toHaveBeenCalledWith("staff");
  });

  it("leaves other 401s alone (wrong password is not an expired token)", async () => {
    const refresh = vi.fn();
    const { authFetch, base } = setup([json(401, { code: "invalid_credentials" })], refresh);
    const r = await authFetch(post("http://x/api/v1/auth/staff/login"));
    expect(r.status).toBe(401);
    expect(refresh).not.toHaveBeenCalled();
    expect(base).toHaveBeenCalledTimes(1);
  });

  it("a suspended account is signed out immediately, without a refresh attempt", async () => {
    const refresh = vi.fn();
    const { authFetch, onUnauthorized } = setup([json(401, { code: "account_suspended" })], refresh);
    await authFetch(post("http://x/api/v1/orgs"));
    expect(refresh).not.toHaveBeenCalled();
    expect(onUnauthorized).toHaveBeenCalledWith("staff");
  });

  it("does not touch 403 or 500 responses", async () => {
    const { authFetch, base } = setup([json(403, { code: "missing_permission" })], async () => "x");
    expect((await authFetch(post("http://x/api/v1/orgs"))).status).toBe(403);
    expect(base).toHaveBeenCalledTimes(1);
  });
});
