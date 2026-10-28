"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";

const reason = (err: unknown, fallback: string) =>
  err instanceof ApiError ? (err.detail ?? err.title) : fallback;

/** Mobile number -> six-digit code. Used to sign in and to attach a phone to a Google account. */
export function OtpFlow({
  submitLabel,
  onVerified,
}: {
  submitLabel: string;
  onVerified: (phone: string, code: string) => Promise<void>;
}) {
  const { requestOtp } = useCustomerSession();
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await requestOtp(phone);
      setCode("");
      setStep("code");
    } catch (err) {
      toast.error(reason(err, "Could not send the code."));
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await onVerified(phone, code);
    } catch (err) {
      toast.error(reason(err, "Could not verify the code."));
    } finally {
      setBusy(false);
    }
  }

  if (step === "phone") {
    return (
      <form onSubmit={send} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="phone">Mobile number</Label>
          <Input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} required />
        </div>
        <Button type="submit" className="w-full" disabled={busy}>Send code</Button>
      </form>
    );
  }
  return (
    <form onSubmit={verify} className="space-y-4">
      <p className="text-sm text-muted-foreground">We sent a 6-digit code to {phone}.</p>
      <div className="space-y-2">
        <Label htmlFor="code">Code</Label>
        <Input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus required />
      </div>
      <Button type="submit" className="w-full" disabled={busy || code.length !== 6}>{submitLabel}</Button>
      <Button type="button" variant="ghost" className="w-full" onClick={() => setStep("phone")}>Use a different number</Button>
    </form>
  );
}
