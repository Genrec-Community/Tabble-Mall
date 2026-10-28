"use client";

import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { storesUpdateStore, type StoreOut, type StoreUpdate } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";

export function StoreProfileForm({
  store,
  canEditProfile,
  canRename,
  onSaved,
}: {
  store: StoreOut;
  canEditProfile: boolean;
  canRename: boolean;
  onSaved: (store: StoreOut) => void;
}) {
  const [name, setName] = useState(store.name);
  const [description, setDescription] = useState(store.description ?? "");

  const save = useMutation({
    mutationFn: async (body: StoreUpdate) => unwrap(await storesUpdateStore({ path: { store_id: store.id }, body })),
    onSuccess: (updated) => {
      toast.success("Saved.");
      onSaved(updated);
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not save."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: StoreUpdate = {};
    if (canRename && name.trim() !== store.name) body.name = name.trim();
    const blurb = description.trim() || null;
    if (canEditProfile && blurb !== (store.description ?? null)) body.description = blurb;
    if (Object.keys(body).length === 0) return;
    save.mutate(body);
  }

  return (
    <form onSubmit={submit} className="max-w-md space-y-4">
      <div className="space-y-2">
        <Label htmlFor="store-name">Name</Label>
        <Input id="store-name" value={name} disabled={!canRename} onChange={(e) => setName(e.target.value)} />
        {!canRename && <p className="text-xs text-muted-foreground">The mall&apos;s team can rename the store.</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="store-description">Description</Label>
        <textarea
          id="store-description"
          rows={4}
          maxLength={500}
          value={description}
          disabled={!canEditProfile}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
        />
      </div>
      {(canEditProfile || canRename) && <Button type="submit" disabled={save.isPending}>Save</Button>}
    </form>
  );
}
