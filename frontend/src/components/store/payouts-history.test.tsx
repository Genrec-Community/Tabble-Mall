import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PayoutsHistory } from "@/components/store/payouts-history";

const api = vi.hoisted(() => ({ paymentsStorePayouts: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("@/components/store/use-store-scope", () => ({ useStoreScope: () => ({ storeId: "s1", scope: { type: "store" } }) }));
vi.mock("@/lib/auth/staff-session", () => ({ useStaffSession: () => ({ can: () => true }) }));

const row = (over: object) => ({
  store_order_id: Math.random().toString(),
  order_label: "#1 · 2026-11-24",
  created_at: "2026-11-24T06:00:00Z",
  order_total_paise: 12000,
  fee_paise: 60,
  payout_paise: 11940,
  transfer_status: "done",
  refund_paise: null,
  refund_status: null,
  ...over,
});

describe("PayoutsHistory", () => {
  it("shows the summary, the fee and what happened to each payout", async () => {
    api.paymentsStorePayouts.mockResolvedValue({
      data: {
        summary: { sales_paise: 24000, fees_paise: 120, paid_out_paise: 23880, on_the_way_paise: 0, failed_paise: 0, taken_back_paise: 11940, refunded_paise: 11940 },
        items: [row({ order_label: "#2 · 2026-11-24" }), row({ refund_paise: 11940, refund_status: "done" })],
        next_cursor: null,
      },
      response: new Response(),
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PayoutsHistory />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Paid to your bank")).toBeTruthy();
    expect(screen.getByText("#2 · 2026-11-24")).toBeTruthy();
    expect(screen.getByText("Paid out")).toBeTruthy();
    expect(screen.getByText("Taken back (refunded)")).toBeTruthy();
    expect(screen.getAllByText(/− ₹0\.60/).length).toBe(2);
  });
});
