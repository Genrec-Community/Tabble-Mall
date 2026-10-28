import { describe, expect, it } from "vitest";
import { ApiError, unwrap } from "@/lib/api-error";

const problem = {
  type: "about:blank",
  title: "Unauthorized",
  status: 401,
  detail: "Wrong username or password.",
  code: "invalid_credentials",
  request_id: "abc",
};

describe("unwrap", () => {
  it("returns the data when the call succeeded", () => {
    expect(unwrap({ data: { ok: 1 }, error: undefined, response: new Response() })).toEqual({ ok: 1 });
  });

  it("throws an ApiError carrying the problem's code, title and detail", () => {
    const response = new Response(null, { status: 401 });
    try {
      unwrap({ data: undefined, error: problem, response });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect([err.status, err.code, err.title, err.detail]).toEqual([
        401,
        "invalid_credentials",
        "Unauthorized",
        "Wrong username or password.",
      ]);
      expect(err.message).toBe("Wrong username or password.");
    }
  });

  it("survives a non-problem error body (e.g. a proxy's HTML page)", () => {
    const response = new Response(null, { status: 502 });
    try {
      unwrap({ data: undefined, error: "<html>Bad gateway</html>", response });
      expect.unreachable();
    } catch (e) {
      const err = e as ApiError;
      expect([err.status, err.code]).toEqual([502, "unknown_error"]);
      expect(err.message).toBe("Something went wrong. Please try again.");
    }
  });

  it("lists field errors from a 422 so forms can show them", () => {
    const response = new Response(null, { status: 422 });
    const error = { ...problem, status: 422, code: "validation_error", detail: null, errors: [{ loc: ["body", "slug"], msg: "bad", type: "x" }] };
    try {
      unwrap({ data: undefined, error, response });
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).fieldErrors).toEqual({ slug: "bad" });
    }
  });
});
