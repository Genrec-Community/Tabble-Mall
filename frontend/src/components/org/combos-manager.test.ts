import { describe, expect, it } from "vitest";
import { comboBody } from "@/components/org/combos-manager";

const burger = { productId: "b", label: "Burger", quantity: 1, pricePaise: 19900 };
const shake = { productId: "s", label: "Shake", quantity: 1, pricePaise: 12900 };

describe("comboBody", () => {
  it("builds the request", () => {
    expect(comboBody(" Burger + shake ", "279", [burger, shake])).toEqual({
      name: "Burger + shake",
      price_paise: 27900,
      items: [
        { product_id: "b", quantity: 1 },
        { product_id: "s", quantity: 1 },
      ],
    });
  });
  it("needs a saving and two dishes", () => {
    expect(comboBody("X", "328", [burger, shake])).toMatch(/less than ₹328/);
    expect(comboBody("X", "100", [burger])).toMatch(/two dishes/);
    expect(comboBody("X", "300", [{ ...burger, quantity: 2 }])).toEqual(expect.objectContaining({ price_paise: 30000 }));
  });
});
