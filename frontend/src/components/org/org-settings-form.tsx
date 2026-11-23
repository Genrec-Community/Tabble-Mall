"use client";

import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { orgsUpdateOrg, type OrgOut, type OrgUpdate } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";

export function OrgSettingsForm({
  org,
  canEditSettings,
  onSaved,
}: {
  org: OrgOut;
  canEditSettings: boolean;
  onSaved: (org: OrgOut) => void;
}) {
  const [name, setName] = useState(org.name);
  const [timeout, setTimeoutS] = useState(String(org.accept_timeout_s));

  const save = useMutation({
    mutationFn: async (body: OrgUpdate) => unwrap(await orgsUpdateOrg({ path: { org_id: org.id }, body })),
    onSuccess: (updated) => {
      toast.success("Saved.");
      onSaved(updated);
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not save."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: OrgUpdate = {};
    if (canEditSettings && name.trim() !== org.name) body.name = name.trim();
    if (canEditSettings && Number(timeout) !== org.accept_timeout_s) body.accept_timeout_s = Number(timeout);
    if (Object.keys(body).length === 0) return;
    save.mutate(body);
  }

  return (
    <form onSubmit={submit} className="max-w-md space-y-4">
      <div className="space-y-2">
        <Label htmlFor="org-name">Name</Label>
        <Input id="org-name" value={name} disabled={!canEditSettings} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="org-timeout">Accept timeout (seconds)</Label>
        <Input id="org-timeout" type="number" min={60} max={3600} value={timeout} disabled={!canEditSettings} onChange={(e) => setTimeoutS(e.target.value)} />
        <p className="text-xs text-muted-foreground">How long a store has to accept a paid order before it is refunded.</p>
      </div>
      {canEditSettings && <Button type="submit" disabled={save.isPending}>Save</Button>}
    </form>
  );
}
