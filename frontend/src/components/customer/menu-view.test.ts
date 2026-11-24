import { describe, expect, it } from "vitest";
import { filterMenu } from "@/components/customer/menu-view";
import type { PublicCategoryOut, PublicProductOut } from "@/lib/api";

const dish = (name: string, description: string | null = null) =>
  ({ id: name, name, description }) as PublicProductOut;
const MENU = [
  {
    id: "a",
    name: "Burgers",
    products: [dish("Cheese Burger", "Double cheddar"), dish("Veg Burger")],
  },
  {
    id: "b",
    name: "Drinks",
    products: [dish("Cold Coffee", "With cheese foam")],
  },
] as PublicCategoryOut[];

describe("filterMenu", () => {
  it("keeps the whole menu when nothing is typed", () => {
    expect(filterMenu(MENU, "  ")).toBe(MENU);
  });
  it("keeps sections that still have a matching dish, matching name, description or section", () => {
    expect(
      filterMenu(MENU, "cheese").map((c) => c.products.map((p) => p.name)),
    ).toEqual([["Cheese Burger"], ["Cold Coffee"]]);
    expect(
      filterMenu(MENU, "burgers veg").map((c) => c.products.map((p) => p.name)),
    ).toEqual([["Veg Burger"]]);
    expect(filterMenu(MENU, "pizza")).toEqual([]);
  });
});
