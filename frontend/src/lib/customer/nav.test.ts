import { describe, expect, it } from "vitest";
import { canGoBack, notePageView, parentOf } from "@/lib/customer/nav";

describe("parentOf", () => {
  it("goes from a restaurant or the cart up to the mall", () => {
    expect(parentOf("/m/demo-mall/s/burger-hub", null)).toBe("/m/demo-mall");
    expect(parentOf("/m/demo-mall/cart", null)).toBe("/m/demo-mall");
  });
  it("has nowhere to go from the mall's home", () => {
    expect(parentOf("/m/demo-mall", "demo-mall")).toBeNull();
  });
  it("goes from an order to the list, and from the account pages to the last mall", () => {
    expect(parentOf("/account/orders/abc", "demo-mall")).toBe(
      "/account/orders",
    );
    expect(parentOf("/account/orders", "demo-mall")).toBe("/m/demo-mall");
    expect(parentOf("/account/login", null)).toBe("/");
  });
});

describe("canGoBack", () => {
  it("is false on the page the customer arrived on, true after an in-app step, and survives a reload", () => {
    window.history.replaceState(null, "");
    notePageView();
    expect(canGoBack()).toBe(false);
    window.history.pushState({ __NA: true }, "", "/m/x/s/y"); // what the router does on a link
    notePageView();
    expect(canGoBack()).toBe(true);
    notePageView(); // a reload or re-render of the same entry keeps its place
    expect(canGoBack()).toBe(true);
    expect((window.history.state as { __NA?: boolean }).__NA).toBe(true); // the router's own state is kept
  });
});
