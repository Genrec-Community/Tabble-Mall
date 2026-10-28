export default function NoAccessPage() {
  return (
    <main className="mx-auto max-w-md space-y-3 p-6">
      <h1 className="text-xl font-semibold">No access yet</h1>
      <p className="text-muted-foreground">
        Your account is active but has no role. Ask the person who manages your team to give you one.
      </p>
    </main>
  );
}
