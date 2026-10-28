"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { OtpFlow } from "@/components/customer/otp-flow";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CustomerMe } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";

export function CustomerAccount() {
  const { status, me, logout, linkPhone } = useCustomerSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "anon") router.replace("/account/login");
  }, [status, router]);

  if (status !== "authed" || !me) return <p className="p-6 text-muted-foreground">Loading…</p>;

  return (
    <main className="mx-auto max-w-md space-y-6 p-4">
      <h1 className="text-xl font-semibold">Your account</h1>

      {me.has_phone ? (
        <p className="text-sm">Mobile number: <span className="font-mono">{me.phone_masked}</span></p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Add your mobile number</CardTitle>
            <CardDescription>We need a verified number before you can place an order.</CardDescription>
          </CardHeader>
          <CardContent>
            <OtpFlow submitLabel="Verify number" onVerified={async (phone, code) => void (await linkPhone(phone, code))} />
          </CardContent>
        </Card>
      )}

      <ProfileForm key={`${me.name}-${me.email}`} me={me} />

      <Button
        variant="outline"
        onClick={async () => {
          await logout();
          router.push("/account/login");
        }}
      >
        Sign out
      </Button>
    </main>
  );
}

function ProfileForm({ me }: { me: CustomerMe }) {
  const { updateProfile } = useCustomerSession();
  const [name, setName] = useState(me.name ?? "");
  const [email, setEmail] = useState(me.email ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const changes: { name?: string; email?: string } = {};
    if (name.trim() && name.trim() !== (me.name ?? "")) changes.name = name.trim();
    if (email.trim() && email.trim() !== (me.email ?? "")) changes.email = email.trim();
    if (Object.keys(changes).length === 0) return;
    setBusy(true);
    try {
      await updateProfile(changes);
      toast.success("Saved.");
    } catch (err) {
      toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="profile-name">Name</Label>
        <Input id="profile-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="profile-email">Email</Label>
        <Input id="profile-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <Button type="submit" disabled={busy}>Save</Button>
    </form>
  );
}
