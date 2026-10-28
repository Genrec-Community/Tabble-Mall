import type { StoreOrderStatus } from "@/lib/api";

/** What each status means to a customer, in the customer's words. */
export const CUSTOMER_STATUS: Record<StoreOrderStatus, string> = {
  pending_payment: "Waiting for payment",
  paid: "Waiting for the store to accept",
  accepted: "Accepted — the store is about to start",
  preparing: "Being prepared",
  ready: "Ready — show your code at the counter",
  picked_up: "Collected",
  rejected: "The store couldn't take this order",
  expired: "The store did not respond in time",
  cancelled: "Cancelled",
  refunded: "Refunded",
  payment_failed: "Payment failed",
};

/** And in the store's words. */
export const STORE_STATUS: Record<StoreOrderStatus, string> = {
  pending_payment: "Awaiting payment",
  paid: "New",
  accepted: "Accepted",
  preparing: "Preparing",
  ready: "Ready for pickup",
  picked_up: "Picked up",
  rejected: "Rejected",
  expired: "Expired",
  cancelled: "Cancelled",
  refunded: "Refunded",
  payment_failed: "Payment failed",
};

/** The pickup code only matters while the order can still be collected. */
export const SHOW_CODE: ReadonlySet<StoreOrderStatus> = new Set(["paid", "accepted", "preparing", "ready"]);
export const OPEN: ReadonlySet<StoreOrderStatus> = SHOW_CODE;
