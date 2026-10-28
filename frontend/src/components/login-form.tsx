"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-error";
import { homePath } from "@/lib/auth/home";
import { safeNext } from "@/lib/auth/safe-next";
import { useStaffSession } from "@/lib/auth/staff-session";

export function LoginForm() {
  const { login } = useStaffSession();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needsTotp, setNeedsTotp] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const me = await login(username, password, needsTotp ? totp : undefined);
      router.push(!me.must_change_password && next ? next : homePath(me));
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") setNeedsTotp(true);
      else toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto mt-16 w-full max-w-sm">
      <CardHeader>
        <CardTitle>Staff sign in</CardTitle>
        <CardDescription>For platform, organization and store teams.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {needsTotp && (
            <div className="space-y-2">
              <Label htmlFor="totp">Authenticator code</Label>
              <Input id="totp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={totp} onChange={(e) => setTotp(e.target.value)} autoFocus required />
            </div>
          )}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
