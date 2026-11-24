import { describe, expect, it } from "vitest";
import { alertFor } from "@/lib/customer-alerts";

const msg = (status: string) => ({ type: "order.updated", store_order_id: "so1", status, order_no: 7 });

describe("alertFor", () => {
  it("tells the customer when a store's part is ready, naming the store", () => {
    const a = alertFor(msg("ready"), "Burger Hub", "o1");
    expect(a?.message).toBe("Burger Hub: your order is ready. Show your pickup code at the counter.");
    expect(a?.urgent).toBe(true);
    expect(a?.href).toBe("/account/orders/o1");
  });

  it("says accepted and rejected too, without a store name if it is unknown", () => {
    expect(alertFor(msg("accepted"), "Chai Point", null)?.message).toBe("Chai Point accepted your order.");
    expect(alertFor(msg("rejected"), null, null)?.message).toBe("The store couldn't take your order. You'll be refunded.");
  });

  it("stays quiet for moves that need nothing from the customer", () => {
    for (const s of ["paid", "preparing", "picked_up", "cancelled", "refunded"]) expect(alertFor(msg(s), "X", null)).toBeNull();
    expect(alertFor({ type: "ping" }, "X", null)).toBeNull();
  });

  it("never carries a pickup code", () => {
    expect(JSON.stringify(alertFor(msg("ready"), "Burger Hub", "o1"))).not.toMatch(/\d{4}/);
  });
});
