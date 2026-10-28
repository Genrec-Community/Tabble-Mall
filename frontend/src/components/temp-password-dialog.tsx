"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface TempSecret {
  username: string;
  password: string;
}

/** Shows a temporary password exactly once; the server never returns it again. */
export function TempPasswordDialog({
  secret,
  onClose,
}: {
  secret: TempSecret | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!secret) return;
    await navigator.clipboard.writeText(secret.password);
    setCopied(true);
  }

  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Temporary password</DialogTitle>
          <DialogDescription>
            Give this to the person now. It is shown only once, and they must choose their own
            password when they first sign in.
          </DialogDescription>
        </DialogHeader>
        {secret && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Username</dt>
            <dd className="font-mono">{secret.username}</dd>
            <dt className="text-muted-foreground">Password</dt>
            <dd className="font-mono select-all">{secret.password}</dd>
          </dl>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            {copied ? "Copied" : "Copy password"}
          </Button>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
