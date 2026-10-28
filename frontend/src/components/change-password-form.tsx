"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authStaffChangePassword } from "@/lib/api";
import { ApiError, ensureOk } from "@/lib/api-error";
import { homePath } from "@/lib/auth/home";
import { useStaffSession } from "@/lib/auth/staff-session";

const MIN_LENGTH = 10;

export function ChangePasswordForm() {
  const { status, me, reload } = useStaffSession();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  if (status === "anon") {
    router.replace("/login");
    return null;
  }
  if (status === "loading" || !me) return <p className="p-6 text-muted-foreground">Loading…</p>;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next.length < MIN_LENGTH) return void toast.error(`Use at least ${MIN_LENGTH} characters.`);
    if (next !== confirm) return void toast.error("The new passwords do not match.");
    setBusy(true);
    try {
      ensureOk(await authStaffChangePassword({ body: { current_password: current, new_password: next } }));
      toast.success("Password changed.");
      const fresh = await reload();
      router.push(fresh ? homePath(fresh) : "/login");
    } catch (err) {
      toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto mt-16 w-full max-w-sm">
      <CardHeader>
        <CardTitle>Choose a new password</CardTitle>
        <CardDescription>
          {me.must_change_password ? "Your password was set for you. Pick your own to continue." : "Change your password."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="current">Current password</Label>
            <Input id="current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new">New password</Label>
            <Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">Repeat new password</Label>
            <Input id="confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Saving…" : "Save password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
