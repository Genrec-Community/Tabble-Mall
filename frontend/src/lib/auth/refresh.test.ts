import { describe, expect, it, vi } from "vitest";
import { createRefresher, type Channel, type LockManager, type Message } from "@/lib/auth/refresh";
import { createTokenStore } from "@/lib/auth/token-store";

/** One lock manager and one broadcast hub shared by every simulated tab. */
function browser() {
  const queues = new Map<string, Promise<unknown>>();
  const locks: LockManager = {
    request<T>(name: string, cb: () => Promise<T>): Promise<T> {
      const run = (queues.get(name) ?? Promise.resolve()).then(cb, cb);
      queues.set(name, run.catch(() => undefined));
      return run;
    },
  };
  const listeners = new Set<(m: Message) => void>();
  const channelFor = (): Channel => {
    const mine = new Set<(m: Message) => void>();
    return {
      post: (m) => listeners.forEach((l) => !mine.has(l) && l(m)),
      onMessage: (l) => {
        mine.add(l);
        listeners.add(l);
      },
    };
  };
  return { locks, channelFor };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("createRefresher", () => {
  it("two simultaneous calls in one tab cause exactly one refresh request", async () => {
    const callRefresh = vi.fn().mockResolvedValue("new-token");
    const store = createTokenStore();
    const r = createRefresher({ callRefresh, store, now: () => 1 });

    const [a, b] = await Promise.all([r.refreshAccess("staff"), r.refreshAccess("staff")]);

    expect([a, b]).toEqual(["new-token", "new-token"]);
    expect(callRefresh).toHaveBeenCalledTimes(1);
    expect(store.get("staff")).toBe("new-token");
  });

  it("two tabs hitting 401 at the same moment refresh once; the second reuses the first's token", async () => {
    const { locks, channelFor } = browser();
    let clock = 0;
    const now = () => ++clock;
    const callRefresh = vi.fn().mockImplementation(async () => {
      await tick();
      return `token-${callRefresh.mock.calls.length}`;
    });
    const tabA = createRefresher({ callRefresh, store: createTokenStore(), locks, channel: channelFor(), now });
    const tabB = createRefresher({ callRefresh, store: createTokenStore(), locks, channel: channelFor(), now });

    const [a, b] = await Promise.all([tabA.refreshAccess("staff"), tabB.refreshAccess("staff")]);

    expect(callRefresh).toHaveBeenCalledTimes(1);
    expect(a).toBe("token-1");
    expect(b).toBe("token-1");
  });

  it("a refresh that starts after another tab already finished does its own refresh", async () => {
    const { locks, channelFor } = browser();
    let clock = 0;
    const now = () => ++clock;
    const callRefresh = vi.fn().mockResolvedValueOnce("first").mockResolvedValueOnce("second");
    const tabA = createRefresher({ callRefresh, store: createTokenStore(), locks, channel: channelFor(), now });
    const tabB = createRefresher({ callRefresh, store: createTokenStore(), locks, channel: channelFor(), now });

    expect(await tabA.refreshAccess("staff")).toBe("first");
    expect(await tabB.refreshAccess("staff")).toBe("second");
    expect(callRefresh).toHaveBeenCalledTimes(2);
  });

  it("staff and customer sessions refresh independently", async () => {
    const { locks, channelFor } = browser();
    const callRefresh = vi.fn().mockImplementation(async (kind: string) => `${kind}-token`);
    const r = createRefresher({ callRefresh, store: createTokenStore(), locks, channel: channelFor(), now: Date.now });
    const [s, c] = await Promise.all([r.refreshAccess("staff"), r.refreshAccess("customer")]);
    expect([s, c]).toEqual(["staff-token", "customer-token"]);
    expect(callRefresh).toHaveBeenCalledTimes(2);
  });

  it("a failed refresh yields null, clears the token, and the next call tries again", async () => {
    const callRefresh = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce("later");
    const store = createTokenStore();
    store.set("staff", "stale");
    const r = createRefresher({ callRefresh, store, now: Date.now });

    expect(await r.refreshAccess("staff")).toBeNull();
    expect(store.get("staff")).toBeNull();
    expect(await r.refreshAccess("staff")).toBe("later");
  });

  it("a thrown error is treated as a failed refresh, not a crash", async () => {
    const r = createRefresher({
      callRefresh: vi.fn().mockRejectedValue(new Error("network down")),
      store: createTokenStore(),
      now: Date.now,
    });
    expect(await r.refreshAccess("staff")).toBeNull();
  });
});
