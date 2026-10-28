"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { GoogleButton } from "@/components/customer/google-button";
import { OtpFlow } from "@/components/customer/otp-flow";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { CustomerMe } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { safeNext } from "@/lib/auth/safe-next";

export function CustomerLogin() {
  const { verifyOtp, googleLogin } = useCustomerSession();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));

  // Ordering needs a verified phone, so a Google sign-in without one lands on the account page.
  const done = (me: CustomerMe) => router.push(me.has_phone && next ? next : "/account");

  return (
    <Card className="mx-auto mt-12 w-full max-w-sm">
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Use your mobile number, or Google.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <OtpFlow submitLabel="Verify and sign in" onVerified={async (phone, code) => done(await verifyOtp(phone, code))} />
        <GoogleButton
          onCredential={async (token) => {
            try {
              done(await googleLogin(token));
            } catch (err) {
              toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Google sign-in failed.");
            }
          }}
        />
      </CardContent>
    </Card>
  );
}
