/** Demo-mode API (DEMO_API=1): serves sample data so the frontend runs without the backend. */
import { DemoError, handleDemo } from "@/lib/demo/data";

export const dynamic = "force-dynamic";

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  if (process.env.DEMO_API !== "1") return new Response(null, { status: 404 });
  const { path } = await context.params;
  const url = new URL(request.url);
  let body: Record<string, unknown> = {};
  if (request.method !== "GET" && request.method !== "DELETE") {
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      body = {};
    }
  }
  try {
    const [status, result] = handleDemo(request.method, `/${path.join("/")}`, body, url.searchParams);
    if (result === undefined) return new Response(null, { status });
    return Response.json(result, {
      status,
      headers: status >= 400 ? { "content-type": "application/problem+json" } : undefined,
    });
  } catch (error) {
    if (error instanceof DemoError) {
      return Response.json(
        { title: error.message, status: error.status, detail: error.message },
        { status: error.status, headers: { "content-type": "application/problem+json" } },
      );
    }
    throw error;
  }
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
