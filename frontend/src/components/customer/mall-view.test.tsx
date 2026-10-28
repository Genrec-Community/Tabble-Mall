import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MallView } from "@/components/customer/mall-view";

describe("MallView", () => {
  it("shows the mall and each of its stores", () => {
    render(
      <MallView
        mall={{
          name: "Phoenix Pune", slug: "phoenix-pune", city: "Pune",
          stores: [
            { name: "Burger Hub", slug: "burger-hub", description: "Best burgers" },
            { name: "Chai Point", slug: "chai-point", description: null },
          ],
        }}
        stores={[
          { slug: "burger-hub", name: "Burger Hub", description: "Best burgers", food_types: ["fast_food", "beverages"], logo_url: null, accepting_orders: true },
          { slug: "chai-point", name: "Chai Point", description: null, food_types: [], logo_url: null, accepting_orders: false },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Phoenix Pune" })).toBeTruthy();
    expect(screen.getByText("Pune")).toBeTruthy();
    expect(screen.getByText("Burger Hub")).toBeTruthy();
    expect(screen.getByText("Best burgers")).toBeTruthy();
    expect(screen.getByText("Chai Point")).toBeTruthy();
    expect(screen.getByText("Fast food · Beverages")).toBeTruthy();
    expect(screen.getByText("Not taking orders")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Burger Hub/ }).getAttribute("href")).toBe("/m/phoenix-pune/s/burger-hub");
  });

  it("says so when no stores are open yet", () => {
    render(<MallView mall={{ name: "New Mall", slug: "new-mall", city: null, stores: [] }} stores={[]} />);
    expect(screen.getByText(/no stores are open/i)).toBeTruthy();
  });
});
