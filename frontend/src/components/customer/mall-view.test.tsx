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
            { name: "Zara", slug: "zara", description: null },
          ],
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Phoenix Pune" })).toBeTruthy();
    expect(screen.getByText("Pune")).toBeTruthy();
    expect(screen.getByText("Burger Hub")).toBeTruthy();
    expect(screen.getByText("Best burgers")).toBeTruthy();
    expect(screen.getByText("Zara")).toBeTruthy();
  });

  it("says so when no stores are open yet", () => {
    render(<MallView mall={{ name: "New Mall", slug: "new-mall", city: null, stores: [] }} />);
    expect(screen.getByText(/no stores are open/i)).toBeTruthy();
  });
});
