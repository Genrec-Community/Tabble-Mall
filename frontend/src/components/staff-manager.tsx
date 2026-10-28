"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DataTable, type Column } from "@/components/data-table";
import { NativeSelect } from "@/components/native-select";
import { TempPasswordDialog, type TempSecret } from "@/components/temp-password-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  staffActivateStaff,
  staffAssignRole,
  staffListRoles,
  staffResetStaffPassword,
  staffRevokeRole,
  staffSuspendStaff,
  type RoleOut,
  type StaffOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { canManage, couldGrant } from "@/lib/auth/grant-rules";
import type { Scope } from "@/lib/auth/permissions";
import { useStaffSession } from "@/lib/auth/staff-session";
import { createStaff, listStaff } from "@/lib/staff-api";

function fail(err: unknown) {
  toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Something went wrong.");
}

/** People who work at one organization, mall or store, and what the viewer may do with them. */
export function StaffManager({ scope }: { scope: Scope }) {
  const { me } = useStaffSession();
  const queryClient = useQueryClient();
  const [secret, setSecret] = useState<TempSecret | null>(null);

  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: async () => unwrap(await staffListRoles()),
    staleTime: 5 * 60_000,
  });
  const staff = useQuery({
    queryKey: ["staff", scope],
    queryFn: async () => unwrap(await listStaff(scope)),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["staff", scope] });
  const act = (run: (s: StaffOut) => Promise<unknown>) => async (s: StaffOut) => {
    try {
      await run(s);
      await refresh();
    } catch (err) {
      fail(err);
    }
  };

  if (!me) return null;
  const allRoles = roles.data ?? [];
  const grantable = allRoles.filter((r) => couldGrant(me.grants, r, scope));

  const suspend = act(async (s) => ensureOk(await staffSuspendStaff({ path: { staff_id: s.id } })));
  const activate = act(async (s) => ensureOk(await staffActivateStaff({ path: { staff_id: s.id } })));
  const reset = act(async (s) => {
    const out = unwrap(await staffResetStaffPassword({ path: { staff_id: s.id } }));
    setSecret({ username: s.username, password: out.temp_password });
  });
  const revoke = (s: StaffOut, assignmentId: string) =>
    act(async () => ensureOk(await staffRevokeRole({ path: { staff_id: s.id, assignment_id: assignmentId } })))(s);

  const columns: Column<StaffOut>[] = [
    {
      header: "Person",
      cell: (s) => (
        <div>
          <span className="font-medium">{s.username}</span>
          <div className="text-xs text-muted-foreground">{s.display_name}</div>
        </div>
      ),
    },
    {
      header: "Roles",
      cell: (s) => {
        const manageable = canManage(me.id, me.grants, s, allRoles);
        return (
          <div className="flex flex-wrap items-center gap-2">
            {s.grants.length === 0 && <span className="text-muted-foreground">None</span>}
            {s.grants.map((g) => (
              <span key={g.id} className="inline-flex items-center gap-1">
                <Badge variant="secondary">{g.role_name}</Badge>
                {manageable && (
                  <ConfirmDialog
                    trigger={
                      <button type="button" aria-label={`Remove ${g.role_name} role`} className="text-muted-foreground hover:text-foreground">
                        ×
                      </button>
                    }
                    title={`Remove the ${g.role_name} role?`}
                    description={`${s.username} will lose the access that role gives them.`}
                    confirmLabel="Yes, remove"
                    destructive
                    onConfirm={() => revoke(s, g.id)}
                  />
                )}
              </span>
            ))}
          </div>
        );
      },
    },
    {
      header: "Status",
      cell: (s) => <Badge variant={s.status === "active" ? "default" : "destructive"}>{s.status}</Badge>,
    },
    {
      header: "",
      className: "text-right",
      cell: (s) => {
        if (!canManage(me.id, me.grants, s, allRoles)) return null;
        return (
          <div className="flex justify-end gap-2">
            {grantable.length > 0 && (
              <AddRoleButton person={s} roles={grantable} scope={scope} onDone={refresh} />
            )}
            <ConfirmDialog
              trigger={<Button variant="outline" size="sm">Reset password</Button>}
              title="Reset this password?"
              description={`${s.username} will be signed out everywhere and given a new temporary password.`}
              confirmLabel="Yes, reset"
              onConfirm={() => reset(s)}
            />
            {s.status === "active" ? (
              <ConfirmDialog
                trigger={<Button variant="outline" size="sm">Suspend</Button>}
                title="Suspend this person?"
                description={`${s.username} will be signed out and unable to sign in until reactivated.`}
                confirmLabel="Yes, suspend"
                destructive
                onConfirm={() => suspend(s)}
              />
            ) : (
              <Button variant="outline" size="sm" onClick={() => activate(s)}>Activate</Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Staff</h2>
        {grantable.length > 0 && (
          <AddStaffButton scope={scope} roles={grantable} onCreated={(s) => { setSecret(s); void refresh(); }} />
        )}
      </div>
      {staff.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : staff.isError ? (
        <p className="text-destructive">Could not load staff.</p>
      ) : (
        <DataTable columns={columns} rows={staff.data ?? []} rowKey={(s) => s.id} empty="No staff yet." />
      )}
      <TempPasswordDialog secret={secret} onClose={() => setSecret(null)} />
    </section>
  );
}

function AddStaffButton({
  scope,
  roles,
  onCreated,
}: {
  scope: Scope;
  roles: RoleOut[];
  onCreated: (secret: TempSecret) => void;
}) {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [roleKey, setRoleKey] = useState(roles[0]?.key ?? "");

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await createStaff(scope, {
          username,
          display_name: displayName,
          email: email.trim() || null,
          role_key: roleKey,
        }),
      ),
    onSuccess: (out) => {
      onCreated({ username: out.staff.username, password: out.temp_password });
      setOpen(false);
      setUsername("");
      setDisplayName("");
      setEmail("");
    },
    onError: fail,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Add staff</Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add staff</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="staff-username">Username</Label>
            <Input id="staff-username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="staff-name">Display name</Label>
            <Input id="staff-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="staff-email">Email (optional)</Label>
            <Input id="staff-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="staff-role">Role</Label>
            <NativeSelect id="staff-role" value={roleKey} onChange={(e) => setRoleKey(e.target.value)}>
              {roles.map((r) => (
                <option key={r.key} value={r.key}>{r.name}</option>
              ))}
            </NativeSelect>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>Create</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddRoleButton({
  person,
  roles,
  scope,
  onDone,
}: {
  person: StaffOut;
  roles: RoleOut[];
  scope: Scope;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [roleKey, setRoleKey] = useState(roles[0]?.key ?? "");

  const assign = useMutation({
    mutationFn: async () =>
      unwrap(
        await staffAssignRole({
          path: { staff_id: person.id },
          body: {
            role_key: roleKey,
            scope_type: scope.type,
            scope_id: scope.store_id ?? scope.mall_id ?? scope.organization_id,
          },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      onDone();
    },
    onError: fail,
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">Add role</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a role for {person.username}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={`role-${person.id}`}>Role</Label>
          <NativeSelect id={`role-${person.id}`} value={roleKey} onChange={(e) => setRoleKey(e.target.value)}>
            {roles.map((r) => (
              <option key={r.key} value={r.key}>{r.name}</option>
            ))}
          </NativeSelect>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={() => assign.mutate()} disabled={assign.isPending}>Add role</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
