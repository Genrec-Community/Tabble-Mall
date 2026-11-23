"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  paymentsGetPayoutAccount,
  paymentsRefreshPayoutAccount,
  paymentsSubmitPayoutAccount,
  type PayoutAccountCreate,
  type PayoutAccountOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

const STATUS: Record<PayoutAccountOut["status"], string> = {
  pending: "Being verified",
  active: "Active",
  disabled: "Not accepted",
};

const EMPTY: PayoutAccountCreate = {
  account_name: "",
  email: "",
  pan: "",
  mcc: "5814",
  business_description: "",
  ifsc: "",
  account_number: "",
};

export function PayoutAccount() {
  const { storeId, scope } = useStoreScope();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const key = ["payout-account", storeId];
  const account = useQuery({
    queryKey: key,
    queryFn: async () => {
      const r = await paymentsGetPayoutAccount({ path: { store_id: storeId } });
      if (r.response?.status === 404) return null;
      return unwrap(r);
    },
    enabled: !!scope && can("store.kyc.submit", scope),
  });
  const refresh = useMutation({
    mutationFn: async () => unwrap(await paymentsRefreshPayoutAccount({ path: { store_id: storeId } })),
    onSuccess: (a) => queryClient.setQueryData(key, a),
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not check the status."),
  });

  if (!scope) return <p className="text-muted-foreground">Loading…</p>;
  if (!can("store.kyc.submit", scope)) return <p className="text-muted-foreground">Only the store owner or organization owner can manage payouts.</p>;
  if (account.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  const a = account.data;

  return (
    <div className="max-w-2xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Payouts</h1>
        <p className="text-sm text-muted-foreground">
          Customers pay MallT once for their whole cart. Your share (your items minus MallT&apos;s commission) is sent to this
          bank account through Zoho Payments as soon as each order is paid. Your store can take orders once the account is active.
        </p>
      </div>
      {a && (
        <section className="space-y-2 rounded-lg border p-4" aria-label="Current payout account">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-medium">{a.account_name}</h2>
            <Badge variant={a.status === "active" ? "default" : "secondary"}>{STATUS[a.status]}</Badge>
          </div>
          <dl className="grid grid-cols-2 gap-1 text-sm">
            <dt className="text-muted-foreground">Bank account</dt><dd>{a.bank_masked} · {a.ifsc}</dd>
            <dt className="text-muted-foreground">PAN</dt><dd>{a.pan_masked}</dd>
            <dt className="text-muted-foreground">Email</dt><dd>{a.email}</dd>
            <dt className="text-muted-foreground">Zoho review</dt><dd>{a.review_status}</dd>
          </dl>
          {a.status !== "active" && (
            <Button size="sm" variant="outline" onClick={() => refresh.mutate()} disabled={refresh.isPending}>Check status</Button>
          )}
        </section>
      )}
      {a?.status !== "active" && <AccountForm storeId={storeId} resubmit={!!a} onSaved={(saved) => queryClient.setQueryData(key, saved)} />}
      {a?.status === "active" && <p className="text-sm text-muted-foreground">To change the bank account, contact MallT support.</p>}
    </div>
  );
}

function AccountForm({ storeId, resubmit, onSaved }: { storeId: string; resubmit: boolean; onSaved: (a: PayoutAccountOut) => void }) {
  const [v, setV] = useState(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: async () => unwrap(await paymentsSubmitPayoutAccount({ path: { store_id: storeId }, body: v })),
    onSuccess: (saved) => {
      setV(EMPTY);
      setErrors({});
      onSaved(saved);
      toast.success(saved.status === "active" ? "Payout account active." : "Submitted. Zoho is verifying the details.");
    },
    onError: (err) => {
      if (err instanceof ApiError) setErrors(err.fieldErrors);
      toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not submit.");
    },
  });
  const field = (name: keyof PayoutAccountCreate, label: string, props: Record<string, unknown> = {}) => (
    <div className="space-y-1">
      <Label htmlFor={`payout-${name}`}>{label}</Label>
      <Input id={`payout-${name}`} value={v[name] ?? ""} onChange={(e) => setV({ ...v, [name]: e.target.value })} aria-invalid={!!errors[name]} required {...props} />
      {errors[name] && <p className="text-xs text-destructive">{errors[name]}</p>}
    </div>
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <h2 className="font-medium">{resubmit ? "Submit corrected details" : "Add your bank account"}</h2>
      {field("account_name", "Business or account holder name")}
      {field("email", "Email for payout notices", { type: "email" })}
      {field("pan", "PAN", { maxLength: 10, autoCapitalize: "characters" })}
      {field("ifsc", "IFSC", { maxLength: 11, autoCapitalize: "characters" })}
      {field("account_number", "Bank account number", { inputMode: "numeric", autoComplete: "off" })}
      {field("business_description", "What you sell", { minLength: 10, maxLength: 1000 })}
      {field("mcc", "Merchant category code (5814 = fast food)", { inputMode: "numeric", maxLength: 4 })}
      <p className="text-xs text-muted-foreground">MallT sends these details to Zoho Payments for verification and keeps only the last four digits.</p>
      <Button type="submit" disabled={save.isPending}>Submit for verification</Button>
    </form>
  );
}
