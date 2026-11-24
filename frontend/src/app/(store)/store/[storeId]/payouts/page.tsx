import { PayoutAccount } from "@/components/store/payout-account";
import { PayoutsHistory } from "@/components/store/payouts-history";

export default function Page() {
  return (
    <div className="space-y-10">
      <PayoutAccount />
      <PayoutsHistory />
    </div>
  );
}
