import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { matchStores } from "@/components/customer/mall-browser";
import { MallView } from "@/components/customer/mall-view";
import type { PublicStoreCardOut } from "@/lib/api";
import {
  CustomerSessionContext,
  type CustomerSession,
} from "@/lib/auth/customer-session";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/m/phoenix-pune",
}));

const items = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  publicPublicItems: items,
}));
afterEach(() => items.mockReset());

const anon = { status: "anon", me: null } as unknown as CustomerSession;

const card = (
  over: Partial<PublicStoreCardOut> & { slug: string; name: string },
): PublicStoreCardOut => ({
  description: null,
  food_types: [],
  logo_url: null,
  banner_url: null,
  accepting_orders: true,
  ...over,
});
const STORES = [
  card({
    slug: "burger-hub",
    name: "Burger Hub",
    description: "Best burgers",
    food_types: ["fast_food", "beverages"],
  }),
  card({
    slug: "chai-point",
    name: "Chai Point",
    food_types: ["beverages"],
    accepting_orders: false,
  }),
];
const MALL = {
  name: "Phoenix Pune",
  slug: "phoenix-pune",
  city: "Pune",
  stores: STORES.map(({ name, slug, description }) => ({
    name,
    slug,
    description,
  })),
};

function show(stores = STORES, mall = MALL) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CustomerSessionContext.Provider value={anon}>
        <MallView mall={mall} stores={stores} />
      </CustomerSessionContext.Provider>
    </QueryClientProvider>,
  );
}

describe("MallView", () => {
  it("lists only restaurants, each linking to its menu, and no dishes", () => {
    show();
    expect(screen.getByRole("heading", { name: "Phoenix Pune" })).toBeTruthy();
    expect(
      screen.getByText(/Pune · 2 restaurants, 1 taking orders now/),
    ).toBeTruthy();
    expect(screen.getByText("Best burgers")).toBeTruthy();
    expect(screen.getByText("Fast food · Beverages")).toBeTruthy();
    expect(screen.getByText("Not taking orders")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Burger Hub/ }).getAttribute("href"),
    ).toBe("/m/phoenix-pune/s/burger-hub");
    expect(
      screen.getByRole("link", { name: /Chai Point/ }).getAttribute("href"),
    ).toBe("/m/phoenix-pune/s/chai-point");
    expect(screen.queryByRole("region", { name: "Dishes" })).toBeNull();
    expect(items).not.toHaveBeenCalled();
  });

  it("searches restaurants and dishes together", async () => {
    items.mockResolvedValue({
      data: {
        items: [
          {
            store_slug: "burger-hub",
            store_name: "Burger Hub",
            accepting_orders: true,
            product: {
              id: "p1",
              name: "Cheese Burger",
              description: null,
              diet: "veg",
              allergens: null,
              prep_minutes: 10,
              image_url: null,
              available: true,
              unavailable_reason: null,
              option_groups: [],
              variants: [
                {
                  id: "v",
                  name: "Regular",
                  price_paise: 12000,
                  available: true,
                },
              ],
            },
          },
        ],
        next_cursor: null,
      },
      error: undefined,
      response: new Response(),
    });
    show();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search restaurants and dishes" }),
      { target: { value: "burger" } },
    );
    expect(
      await screen.findByRole("button", {
        name: "Add Cheese Burger from Burger Hub",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: /Burger Hub/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Chai Point/ })).toBeNull();
    expect(items.mock.calls[0][0].query.q).toBe("burger");
  });

  it("says nothing matches when neither a restaurant nor a dish does", async () => {
    items.mockResolvedValue({
      data: { items: [], next_cursor: null },
      error: undefined,
      response: new Response(),
    });
    show();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search restaurants and dishes" }),
      { target: { value: "sushi" } },
    );
    await waitFor(() =>
      expect(screen.getByText("Nothing matches")).toBeTruthy(),
    );
  });

  it("says so when no stores are open yet", () => {
    show([], { name: "New Mall", slug: "new-mall", city: "", stores: [] });
    expect(screen.getByText(/no stores are open/i)).toBeTruthy();
  });
});

describe("matchStores", () => {
  it("matches every word against name, description and cuisine, and filters by cuisine", () => {
    expect(matchStores(STORES, "best", null).map((s) => s.slug)).toEqual([
      "burger-hub",
    ]);
    expect(matchStores(STORES, "beverages", null).map((s) => s.slug)).toEqual([
      "burger-hub",
      "chai-point",
    ]);
    expect(
      matchStores(STORES, "chai beverages", null).map((s) => s.slug),
    ).toEqual(["chai-point"]);
    expect(matchStores(STORES, "", "fast_food").map((s) => s.slug)).toEqual([
      "burger-hub",
    ]);
  });
});
