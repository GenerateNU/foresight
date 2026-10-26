"""Domain errors raised by services, mapped to HTTP status codes.

The only place a service error becomes a status code. Every error body is
`{"detail": "..."}`, the same shape FastAPI uses for its own errors.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from foresight.services.errors import (
    ConflictError,
    DomainError,
    InvalidRequestError,
    NotConfiguredError,
    NotFoundError,
)

_STATUS: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidRequestError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


async def _handle(_: Request, exc: Exception) -> JSONResponse:
    code = next(c for kind, c in _STATUS.items() if isinstance(exc, kind))
    return JSONResponse({"detail": str(exc)}, status_code=code)


def register_error_handlers(app: FastAPI) -> None:
    for kind in _STATUS:
        app.add_exception_handler(kind, _handle)
