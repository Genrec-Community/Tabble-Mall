/** Turns the SDK's `{ data, error }` results into values or thrown, readable errors. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly title: string,
    readonly detail: string | null,
    readonly fieldErrors: Record<string, string> = {},
  ) {
    super(detail ?? title);
    this.name = "ApiError";
  }
}

interface Problem {
  title?: string;
  status?: number;
  detail?: string | null;
  code?: string;
  errors?: { loc: (string | number)[]; msg: string }[];
}

export interface SdkResult<T> {
  data?: T;
  error?: unknown;
  response?: Response;
}

const FALLBACK = "Something went wrong. Please try again.";

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && "code" in value;
}

export function toApiError(error: unknown, response?: Response): ApiError {
  const status = response?.status ?? 0;
  if (!isProblem(error)) return new ApiError(status, "unknown_error", FALLBACK, FALLBACK);
  const fieldErrors: Record<string, string> = {};
  for (const e of error.errors ?? []) fieldErrors[e.loc.slice(1).join(".")] = e.msg;
  return new ApiError(
    error.status ?? status,
    error.code ?? "unknown_error",
    error.title ?? FALLBACK,
    error.detail ?? null,
    fieldErrors,
  );
}

/** The data of a successful call; throws an ApiError otherwise. */
export function unwrap<T>(result: SdkResult<T>): T {
  if (result.error !== undefined) throw toApiError(result.error, result.response);
  return result.data as T;
}

/** For calls with no body in the response (204). */
export function ensureOk(result: SdkResult<unknown>): void {
  if (result.error !== undefined) throw toApiError(result.error, result.response);
}
