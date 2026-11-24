/**
 * Zoho Payments checkout widget (zpayments.js). The browser only collects a payment id here;
 * the server asks Zoho whether that payment really succeeded before the order counts as paid.
 */
import type { ZohoCheckoutOut } from "@/lib/api";

export const ZOHO_SCRIPT = "https://static.zohocdn.com/zpay/zpay-js/v1/zpayments.js";

interface ZohoResult {
  payment_id?: string;
  message?: string;
}

interface ZohoError {
  code?: string;
  message?: string;
}

interface ZohoInstance {
  requestPaymentMethod(options: Record<string, unknown>): Promise<ZohoResult>;
  close?: () => Promise<void> | void;
}

type ZohoCtor = new (config: Record<string, unknown>) => ZohoInstance;

declare global {
  interface Window {
    ZPayments?: ZohoCtor;
  }
}

/** Thrown when the customer closed the widget or Zoho refused; `closed` means no harm done. */
export class ZohoPaymentError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ZohoPaymentError";
  }
  get closed(): boolean {
    return this.code === "widget_closed";
  }
}

let loading: Promise<ZohoCtor> | null = null;

export function loadZoho(doc: Document = document): Promise<ZohoCtor> {
  if (typeof window !== "undefined" && window.ZPayments) return Promise.resolve(window.ZPayments);
  loading ??= new Promise<ZohoCtor>((resolve, reject) => {
    const script = doc.createElement("script");
    script.src = ZOHO_SCRIPT;
    script.async = true;
    script.onload = () => (window.ZPayments ? resolve(window.ZPayments) : reject(new Error("Zoho checkout did not load")));
    script.onerror = () => {
      loading = null;
      reject(new Error("Could not load Zoho checkout. Check your connection and try again."));
    };
    doc.head.appendChild(script);
  });
  return loading;
}

export interface Payer {
  name?: string | null;
  phone?: string | null;
}

/** Opens Zoho's checkout and resolves with the payment id Zoho returns. */
export async function payWithZoho(params: ZohoCheckoutOut, payer: Payer = {}): Promise<string> {
  const ZPayments = await loadZoho();
  const instance = new ZPayments({
    account_id: params.account_id,
    domain: params.domain,
    otherOptions: { api_key: params.api_key, ...(params.is_test_mode ? { is_test_mode: true } : {}) },
  });
  try {
    const result = await instance.requestPaymentMethod({
      amount: params.amount,
      currency_code: params.currency_code,
      payments_session_id: params.payments_session_id,
      description: params.description,
      // Prefilled from the customer's own account so they don't type their number again.
      address: { name: params.name ?? payer.name ?? undefined, phone: params.phone ?? payer.phone ?? undefined },
    });
    if (!result.payment_id) throw new ZohoPaymentError("no_payment", result.message ?? "The payment did not complete.");
    return result.payment_id;
  } catch (err) {
    if (err instanceof ZohoPaymentError) throw err;
    const e = (err ?? {}) as ZohoError;
    throw new ZohoPaymentError(e.code ?? "unknown", e.message ?? "The payment did not complete.");
  } finally {
    await instance.close?.();
  }
}
