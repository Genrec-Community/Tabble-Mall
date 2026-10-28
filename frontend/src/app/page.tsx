import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">MallT</h1>
      <p className="text-muted-foreground">Staff and customers sign in from here.</p>
      <Link className="underline" href="/login">Staff sign in</Link>
      <Link className="underline" href="/account/login">Customer sign in</Link>
    </main>
  );
}
