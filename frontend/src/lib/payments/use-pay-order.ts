"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ordersConfirmMyPayment, type CustomerOrderOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { payWithZoho, ZohoPaymentError, type Payer } from "@/lib/payments/zoho";

/** Pay an order that is waiting for payment: open the provider's checkout, then let the server
 * confirm with the provider. Resolves with the updated order (still "placed" if not paid). */
export function usePayOrder(payer: Payer = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (order: CustomerOrderOut): Promise<CustomerOrderOut> => {
      const zoho = order.payment?.zoho;
      if (!zoho) return order;
      const paymentId = await payWithZoho(zoho, payer);
      return unwrap(await ordersConfirmMyPayment({ path: { order_id: order.id }, body: { payment_id: paymentId } }));
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["my-order", updated.id], updated);
      if (updated.status === "paid") toast.success("Paid. The stores have your order.");
    },
    onError: (err) => {
      if (err instanceof ZohoPaymentError && err.closed) return; // the customer closed it
      toast.error(err instanceof ApiError || err instanceof Error ? ((err instanceof ApiError ? err.detail : null) ?? err.message) : "The payment did not go through.");
    },
  });
}
