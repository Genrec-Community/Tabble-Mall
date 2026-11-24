import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { groupByStore, MallItems } from "@/components/customer/mall-items";
import type { PublicItemOut } from "@/lib/api";
import { CustomerSessionContext, type CustomerSession } from "@/lib/auth/customer-session";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/m/phoenix",
}));
beforeEach(() => push.mockReset());

const anon = { status: "anon", me: null } as unknown as CustomerSession;

const item = (over: Partial<PublicItemOut> & { name: string }): PublicItemOut => ({
  store_slug: "burger-hub",
  store_name: "Burger Hub",
  accepting_orders: true,
  ...over,
  product: {
    id: over.name,
    name: over.name,
    description: null,
    diet: "veg",
    allergens: null,
    prep_minutes: 10,
    image_url: null,
    available: true,
    unavailable_reason: null,
    variants: [{ id: "v", name: "Regular", price_paise: 12000, available: true }, { id: "w", name: "Large", price_paise: 18000, available: true }],
    option_groups: [],
    ...over.product,
  },
});

function show(items: PublicItemOut[]) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CustomerSessionContext.Provider value={anon}>
        <MallItems mallSlug="phoenix" foodTypes={["fast_food", "beverages"]} initial={{ items, next_cursor: null }} />
      </CustomerSessionContext.Provider>
    </QueryClientProvider>,
  );
}

describe("MallItems", () => {
  it("lists dishes with their store, a from-price and filter chips", () => {
    show([item({ name: "Cheese Burger" })]);
    expect(screen.getByText("Cheese Burger")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Burger Hub" }).getAttribute("href")).toBe("/m/phoenix/s/burger-hub");
    expect(screen.getByText(/From ₹120\.00/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Veg only" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fast food" })).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "Search dishes" })).toBeTruthy();
  });

  it("cannot add from a store that is not taking orders, or a sold-out dish", () => {
    show([
      item({ name: "Closed Dish", accepting_orders: false }),
      item({ name: "Samosa", product: { available: false, unavailable_reason: "sold_out" } as never }),
    ]);
    expect((screen.getByRole("button", { name: /Add Closed Dish/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /Add Samosa/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Store not taking orders")).toBeTruthy();
    expect(screen.getByText("Sold out")).toBeTruthy();
  });

  it("says so when there are no dishes", () => {
    show([]);
    expect(screen.getByText(/No dishes yet/)).toBeTruthy();
  });

  it("groups dishes under their store, in order of first appearance", () => {
    show([item({ name: "Cheese Burger" }), item({ name: "Masala Chai", store_slug: "chai-point", store_name: "Chai Point" }), item({ name: "Fries" })]);
    const burger = screen.getByRole("region", { name: "Burger Hub" });
    expect(within(burger).getByText("Cheese Burger")).toBeTruthy();
    expect(within(burger).getByText("Fries")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Chai Point" })).getByText("Masala Chai")).toBeTruthy();
  });

  it("adds a one-size dish in one tap (a visitor is sent to sign in first), and opens the sheet for a dish with sizes", () => {
    const simple = { variants: [{ id: "v", name: "Regular", price_paise: 3000, available: true }] } as never;
    show([item({ name: "Masala Chai", product: simple }), item({ name: "Cheese Burger" })]);
    fireEvent.click(screen.getByRole("button", { name: "Add Masala Chai" }));
    expect(push).toHaveBeenCalledWith("/account/login?next=%2Fm%2Fphoenix");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add Cheese Burger" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByLabelText(/Large/)).toBeTruthy();
  });

  it("shows a dish's photo when it has one, and a plate with its initial otherwise", () => {
    show([item({ name: "Photo Dish", product: { image_url: "https://cdn.example/p.jpg" } as never }), item({ name: "Plain Dish" })]);
    expect(document.querySelector('img[src="https://cdn.example/p.jpg"]')).toBeTruthy();
    expect(screen.getByText("P", { selector: "span" })).toBeTruthy();
  });
});

describe("groupByStore", () => {
  it("keeps the mall's store order and can include stores with no dishes", () => {
    const stores = [
      { slug: "a", name: "A", description: null, food_types: [], logo_url: null, accepting_orders: true },
      { slug: "b", name: "B", description: null, food_types: [], logo_url: null, accepting_orders: false },
    ];
    const groups = groupByStore([item({ name: "x", store_slug: "b", store_name: "B" })], stores, true);
    expect(groups.map((g) => [g.slug, g.items.length])).toEqual([["a", 0], ["b", 1]]);
    expect(groupByStore([item({ name: "x", store_slug: "b", store_name: "B" })], stores, false).map((g) => g.slug)).toEqual(["b"]);
  });
});
