import type { LiveMessage } from "@/lib/live";

export interface OrderAlert {
  /** Distinct per event, so a second alert re-shows rather than silently replacing the first. */
  id: string;
  message: string;
  /** Ready is the one worth a buzz: the customer has to walk to the counter. */
  urgent: boolean;
  href: string | null;
}

/**
 * What is worth interrupting a customer with when one of their store orders moves, in one tested
 * place (after Tabble's diner notices). `storeName` comes from the customer's own order list.
 * Their own cancel, refunds and the moves they are waiting through (preparing) stay quiet.
 */
export function alertFor(message: LiveMessage, storeName: string | null, orderId: string | null): OrderAlert | null {
  if (!message.store_order_id || !message.status) return null;
  const who = storeName ?? "The store";
  const id = `${message.store_order_id}-${message.status}`;
  const href = orderId ? `/account/orders/${orderId}` : "/account/orders";
  switch (message.status) {
    case "accepted":
      return { id, message: `${who} accepted your order.`, urgent: false, href };
    case "ready":
      return { id, message: `${who}: your order is ready. Show your pickup code at the counter.`, urgent: true, href };
    case "rejected":
      return { id, message: `${who} couldn't take your order. You'll be refunded.`, urgent: true, href };
    case "expired":
      return { id, message: `${who} didn't respond in time. You'll be refunded.`, urgent: true, href };
    default:
      return null;
  }
}
