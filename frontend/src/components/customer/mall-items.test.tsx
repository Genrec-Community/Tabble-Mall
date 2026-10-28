import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MallItems } from "@/components/customer/mall-items";
import type { PublicItemOut } from "@/lib/api";

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
      <MallItems mallSlug="phoenix" foodTypes={["fast_food", "beverages"]} initial={{ items, next_cursor: null }} />
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
});
