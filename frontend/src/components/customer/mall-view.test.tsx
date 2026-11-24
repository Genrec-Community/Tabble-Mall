import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { matchStores, sortStores } from "@/components/customer/mall-browser";
import { MallView } from "@/components/customer/mall-view";
import type { PopularItemOut, PublicStoreCardOut } from "@/lib/api";
import {
  CustomerSessionContext,
  type CustomerSession,
} from "@/lib/auth/customer-session";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/m/phoenix-pune",
  useSearchParams: () => new URLSearchParams(),
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
  pickup_point: null,
  prep_minutes: null,
  top_dishes: [],
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

function show(stores = STORES, mall = MALL, popular: PopularItemOut[] = [], featured?: { rail: boolean; first: boolean }) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CustomerSessionContext.Provider value={anon}>
        <MallView mall={mall} stores={stores} popular={popular} featured={featured} />
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

  it("filters to quick-ready restaurants and shows popular dishes as links, never add buttons", () => {
    const burger = {
      store_slug: "burger-hub",
      store_name: "Burger Hub",
      accepting_orders: true,
      orders: 9,
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
        variants: [{ id: "v", name: "Regular", price_paise: 12000, available: true }],
      },
    } as PopularItemOut;
    show(
      [
        card({ slug: "burger-hub", name: "Burger Hub", prep_minutes: 10, top_dishes: ["Cheese Burger"] }),
        card({ slug: "slow-pot", name: "Slow Pot", prep_minutes: 40 }),
      ],
      MALL,
      [burger],
    );
    const popular = screen.getByRole("region", { name: "Popular in the mall" });
    expect(popular.querySelector("a")?.getAttribute("href")).toBe("/m/phoenix-pune/s/burger-hub");
    expect(screen.queryByRole("button", { name: /Add Cheese Burger/ })).toBeNull();
    expect(screen.getByText("Ready in ~10 min")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Under 15 min" }));
    expect(screen.queryByRole("link", { name: /Slow Pot/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Burger Hub/ })).toBeTruthy();
    // Filtering hides the rails, so the page is just the matching restaurants.
    expect(screen.queryByRole("region", { name: "Popular in the mall" })).toBeNull();
  });

  it("shows paid featured spots only where the owner switched them on, and quietly", () => {
    const stores = [STORES[0], { ...STORES[1], accepting_orders: true, featured: true, featured_rank: 0 }];
    show(stores, MALL, [], { rail: false, first: false });
    expect(screen.queryByRole("region", { name: "Featured restaurants" })).toBeNull();
    expect(screen.queryByText("Featured")).toBeNull();
  });

  it("puts a slim featured row above the list and featured stores first when switched on", () => {
    const stores = [STORES[0], { ...STORES[1], accepting_orders: true, featured: true, featured_rank: 0 }];
    show(stores, MALL, [], { rail: true, first: true });
    const rail = screen.getByRole("region", { name: "Featured restaurants" });
    expect(rail.querySelectorAll("li")).toHaveLength(1);
    expect(rail.textContent).toContain("Chai Point");
    const list = screen.getByRole("region", { name: "Restaurants" });
    const names = [...list.querySelectorAll("li")].map((li) => li.textContent ?? "");
    expect(names[0]).toContain("Chai Point");
    expect(names[0]).toContain("Featured");
    expect(names[1]).not.toContain("Featured");
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

describe("sortStores", () => {
  it("puts open restaurants first, then sorts by ready time or name", () => {
    const list = [
      card({ slug: "b", name: "Bravo", prep_minutes: 20 }),
      card({ slug: "a", name: "Alpha", prep_minutes: 30 }),
      card({ slug: "c", name: "Closed", prep_minutes: 5, accepting_orders: false }),
      card({ slug: "d", name: "Delta", prep_minutes: 10 }),
    ];
    expect(sortStores(list, "recommended").map((s) => s.slug)).toEqual(["b", "a", "d", "c"]);
    expect(sortStores(list, "fastest").map((s) => s.slug)).toEqual(["d", "b", "a", "c"]);
    expect(sortStores(list, "name").map((s) => s.slug)).toEqual(["a", "b", "d", "c"]);
  });

  it("lifts featured stores to the top of the recommended order only when asked", () => {
    const list = [
      card({ slug: "b", name: "Bravo" }),
      card({ slug: "a", name: "Alpha", featured: true, featured_rank: 1 }),
      card({ slug: "d", name: "Delta", featured: true, featured_rank: 0 }),
      card({ slug: "c", name: "Closed", featured: true, featured_rank: 2, accepting_orders: false }),
    ];
    expect(sortStores(list, "recommended").map((s) => s.slug)).toEqual(["b", "a", "d", "c"]);
    expect(sortStores(list, "recommended", true).map((s) => s.slug)).toEqual(["d", "a", "b", "c"]);
    expect(sortStores(list, "name", true).map((s) => s.slug)).toEqual(["a", "b", "d", "c"]);
  });
});
