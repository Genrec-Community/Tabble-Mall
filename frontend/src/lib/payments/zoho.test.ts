import { afterEach, describe, expect, it, vi } from "vitest";
import { payWithZoho, ZohoPaymentError } from "@/lib/payments/zoho";

const params = {
  account_id: "123",
  api_key: "pub",
  domain: "IN",
  is_test_mode: true,
  payments_session_id: "555",
  amount: "430.00",
  currency_code: "INR",
  description: "Order 1",
};

function install(requestPaymentMethod: (o: Record<string, unknown>) => Promise<unknown>) {
  const configs: Record<string, unknown>[] = [];
  const calls: Record<string, unknown>[] = [];
  const close = vi.fn();
  window.ZPayments = class {
    constructor(config: Record<string, unknown>) {
      configs.push(config);
    }
    requestPaymentMethod(o: Record<string, unknown>) {
      calls.push(o);
      return requestPaymentMethod(o) as Promise<{ payment_id?: string }>;
    }
    close = close;
  };
  return { configs, calls, close };
}

afterEach(() => {
  delete window.ZPayments;
});

describe("payWithZoho", () => {
  it("opens the widget with the server's session and returns the payment id", async () => {
    const z = install(async () => ({ payment_id: "777" }));
    await expect(payWithZoho(params, { name: "Asha", phone: "+91••••9061" })).resolves.toBe("777");
    expect(z.configs[0]).toEqual({ account_id: "123", domain: "IN", otherOptions: { api_key: "pub", is_test_mode: true } });
    expect(z.calls[0]).toMatchObject({ amount: "430.00", currency_code: "INR", payments_session_id: "555" });
    expect(z.close).toHaveBeenCalled();
  });

  it("prefills the customer's own phone from the server so they don't type it again", async () => {
    const z = install(async () => ({ payment_id: "1" }));
    await payWithZoho({ ...params, phone: "9876543210", name: "Asha" });
    expect(z.calls[0]).toMatchObject({ address: { name: "Asha", phone: "9876543210" } });
  });

  it("reports a closed widget so the page can offer to pay again", async () => {
    install(async () => {
      throw { code: "widget_closed", message: "closed" };
    });
    const err = await payWithZoho(params).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ZohoPaymentError);
    expect((err as ZohoPaymentError).closed).toBe(true);
  });

  it("treats a missing payment id as a failure", async () => {
    install(async () => ({ message: "declined" }));
    await expect(payWithZoho(params)).rejects.toThrow("declined");
  });
});
