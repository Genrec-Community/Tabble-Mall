import { describe, expect, it } from "vitest";
import { bestOffer, describeOffer, offerHeadline, rupees } from "@/lib/offers";

describe("offers in words", () => {
  it("shows short rupees", () => {
    expect(rupees(5000)).toBe("₹50");
    expect(rupees(4950)).toBe("₹49.50");
    expect(rupees(150000)).toBe("₹1,500");
  });

  it("describes percent and flat offers", () => {
    expect(offerHeadline({ kind: "percent", value: 2000, max_discount_paise: 5000 })).toBe("20% off up to ₹50");
    expect(offerHeadline({ kind: "percent", value: 1250 })).toBe("12.5% off");
    expect(offerHeadline({ kind: "flat", value: 4000 })).toBe("₹40 off");
    expect(describeOffer({ kind: "flat", value: 4000, min_subtotal_paise: 19900, code: "CHAI40" })).toBe(
      "₹40 off · above ₹199 · code CHAI40",
    );
  });

  it("prefers an automatic offer for the card badge", () => {
    const coupon = { kind: "percent", value: 5000, code: "BIG" };
    const auto = { kind: "percent", value: 1000, code: null };
    expect(bestOffer([coupon, auto])).toBe(auto);
    expect(bestOffer([])).toBeUndefined();
  });
});
