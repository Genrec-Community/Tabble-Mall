import { describe, expect, it } from "vitest";
import { toProductBody } from "@/components/store/product-form";

const base = {
  name: "  Cheese Burger ",
  description: "",
  categoryId: "",
  diet: "veg" as const,
  allergens: "",
  prep: "12",
  taxPct: "5",
  stockMode: "manual" as const,
  imageKey: null,
  window: null,
  variants: [{ name: "Regular", price: "120.50", stock: "" }],
  groups: [] as { id?: string; name: string; min: number; max: number; options: { id?: string; name: string; delta: string }[] }[],
};

describe("toProductBody", () => {
  it("turns the form into the API body in paise", () => {
    const body = toProductBody({
      ...base,
      groups: [{ name: "Extras", min: 0, max: 2, options: [{ name: "Cheese", delta: "20" }, { name: "Jalapeno", delta: "" }] }],
    });
    expect(body).toMatchObject({
      name: "Cheese Burger",
      description: null,
      category_id: null,
      prep_minutes: 12,
      tax_bps: 500,
      stock_mode: "manual",
      variants: [{ name: "Regular", price_paise: 12050, stock_count: null }],
      option_groups: [{ name: "Extras", min_select: 0, max_select: 2, options: [{ name: "Cheese", price_delta_paise: 2000 }, { name: "Jalapeno", price_delta_paise: 0 }] }],
    });
  });

  it("needs a stock number for every size of a counted item, and ignores it otherwise", () => {
    expect(toProductBody({ ...base, stockMode: "counted" })).toMatch(/stock number/);
    const ok = toProductBody({ ...base, stockMode: "counted", variants: [{ name: "Pack", price: "10", stock: "7" }] });
    expect(ok).toMatchObject({ variants: [{ stock_count: 7 }] });
    expect(toProductBody({ ...base, variants: [{ name: "Regular", price: "10", stock: "99" }] })).toMatchObject({ variants: [{ stock_count: null }] });
  });

  it("explains what to fix instead of sending a bad body", () => {
    expect(toProductBody({ ...base, variants: [{ name: "", price: "10", stock: "" }] })).toMatch(/needs a name and a price/);
    expect(toProductBody({ ...base, variants: [{ name: "R", price: "ten", stock: "" }] })).toMatch(/needs a name and a price/);
    expect(toProductBody({ ...base, groups: [{ name: "X", min: 0, max: 1, options: [] }] })).toMatch(/at least one option/);
    expect(toProductBody({ ...base, groups: [{ name: "X", min: 2, max: 1, options: [{ name: "a", delta: "" }] }] })).toMatch(/limits/);
    expect(toProductBody({ ...base, groups: [{ name: "X", min: 0, max: 1, options: [{ name: "a", delta: "1.234" }] }] })).toMatch(/Check the options/);
  });

  it("keeps ids so an edit does not recreate sizes and options", () => {
    const body = toProductBody({
      ...base,
      variants: [{ id: "v1", name: "Regular", price: "10", stock: "" }],
      groups: [{ id: "g1", name: "Extras", min: 0, max: 1, options: [{ id: "o1", name: "Cheese", delta: "5" }] }],
    });
    expect(body).toMatchObject({ variants: [{ id: "v1" }], option_groups: [{ id: "g1", options: [{ id: "o1" }] }] });
  });
});
