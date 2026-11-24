import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FoodMark, QuickAdd, glyphKeyFor, withVariant } from "@/components/customer/lux";

describe("withVariant", () => {
  it("hides the default size and keeps a real one", () => {
    expect(withVariant("Cheese Burger", "Regular")).toBe("Cheese Burger");
    expect(withVariant("Cheese Burger", "Large")).toBe("Cheese Burger (Large)");
    expect(withVariant("Chai", null)).toBe("Chai");
  });
});

describe("QuickAdd", () => {
  it("is one + until the dish is in the cart, then a stepper whose − at one removes it", () => {
    const onChange = vi.fn();
    const { rerender } = render(<QuickAdd name="Chai" quantity={0} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Chai" }));
    expect(onChange).toHaveBeenLastCalledWith(1);
    rerender(<QuickAdd name="Chai" quantity={1} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove Chai" }));
    expect(onChange).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "One more Chai" }));
    expect(onChange).toHaveBeenLastCalledWith(2);
  });

  it("stops at 20", () => {
    render(<QuickAdd name="Chai" quantity={20} onChange={() => undefined} />);
    expect((screen.getByRole("button", { name: "One more Chai" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("FoodMark and glyphs", () => {
  it("labels the diet mark for screen readers", () => {
    render(<FoodMark diet="nonveg" />);
    expect(screen.getByRole("img", { name: "Non-vegetarian" })).toBeTruthy();
  });
  it("picks a glyph from the dish or section name", () => {
    expect(glyphKeyFor("Masala Chai Beverages")).toBe("drink");
    expect(glyphKeyFor("Cheese Burger")).toBe("bread");
    expect(glyphKeyFor("Mystery")).toBe("default");
  });
});
