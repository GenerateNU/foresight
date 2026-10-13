from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from scalar_fastapi import Theme, get_scalar_api_reference

from foresight.config import settings
from foresight.routes import example_widget, health, hotels, signals
from foresight.services.errors import ConflictError, NotFoundError

app = FastAPI(
    title=settings.app_name,
    description="AI revenue intelligence platform for boutique hotels",
    version="0.1.0",
    # Use Scalar for the API reference instead of the built-in Swagger UI.
    docs_url=None,
)


# Services raise domain errors; this is the one place they become HTTP.
@app.exception_handler(NotFoundError)
async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(ConflictError)
async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_409_CONFLICT)


app.include_router(health.router)
app.include_router(hotels.router)
app.include_router(signals.router)
app.include_router(example_widget.router)


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
        theme=Theme.DEEP_SPACE,
    )
