import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mallt.core.logging import get_request_id

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status = 500
    default_code = "internal_error"
    default_title = "Internal Server Error"
    # When True, get_session commits the request's work instead of rolling it back. Only for
    # errors whose side effects must persist (e.g. revoking a session after token reuse).
    commit_on_error = False

    def __init__(
        self,
        code: str | None = None,
        detail: str | None = None,
        *,
        title: str | None = None,
        extra: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.title = title or self.default_title
        self.detail = detail
        self.extra = extra or {}
        if status is not None:
            self.status = status
        super().__init__(self.code)

    def headers(self) -> dict[str, str]:
        return {}


class BadRequest(AppError):
    status, default_code, default_title = 400, "bad_request", "Bad Request"


class Unauthorized(AppError):
    status, default_code, default_title = 401, "unauthorized", "Unauthorized"


class Forbidden(AppError):
    status, default_code, default_title = 403, "forbidden", "Forbidden"


class NotFound(AppError):
    status, default_code, default_title = 404, "not_found", "Not Found"


class Conflict(AppError):
    status, default_code, default_title = 409, "conflict", "Conflict"


class Unprocessable(AppError):
    status, default_code, default_title = 422, "unprocessable", "Unprocessable Entity"


class RateLimited(AppError):
    status, default_code, default_title = 429, "rate_limited", "Too Many Requests"

    def __init__(self, retry_after: int, code: str | None = None) -> None:
        super().__init__(code, extra={"retry_after": retry_after})
        self.retry_after = retry_after

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}


def problem(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": get_request_id(),
        **(extra or {}),
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, exc.extra, exc.headers())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(422, "validation_error", "Validation Failed", None, {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return problem(exc.status_code, code, str(exc.detail), None, None, exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return problem(500, "internal_error", "Internal Server Error")
