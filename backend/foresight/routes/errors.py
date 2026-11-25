from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from foresight.services.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    InvalidRequestError,
    NotConfiguredError,
    NotFoundError,
    NotSignedInError,
)

_STATUS: dict[type[DomainError], int] = {
    NotSignedInError: status.HTTP_401_UNAUTHORIZED,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidRequestError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


async def _handle(_: Request, exc: Exception) -> JSONResponse:
    """Turns a service error into its status code and a `{"detail": ...}` body.

    The same shape FastAPI uses for its own errors.

    Args:
        _ (Request): Unused.
        exc (Exception): The service error.

    Returns:
        JSONResponse: The error response.
    """
    code = next(c for kind, c in _STATUS.items() if isinstance(exc, kind))
    return JSONResponse({"detail": str(exc)}, status_code=code)


def register_error_handlers(app: FastAPI) -> None:
    """Maps every service error to its status code; the only place this happens.

    Args:
        app (FastAPI): The app.
    """
    for kind in _STATUS:
        app.add_exception_handler(kind, _handle)
