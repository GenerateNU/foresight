"""App setup: routers, error handling, lifespan, and the API reference."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from scalar_fastapi import Theme, get_scalar_api_reference

from foresight import worker
from foresight.config import settings
from foresight.routes import (
    city,
    event,
    example_widget,
    flight,
    health,
    hotel,
    ingest,
    job,
    pricing_model,
    weather,
)
from foresight.routes.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Background jobs die with the process; anything left running is stale.
    await worker.fail_interrupted_jobs()
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI revenue intelligence platform for boutique hotels",
    version="0.1.0",
    # Use Scalar for the API reference instead of the built-in Swagger UI.
    docs_url=None,
    lifespan=lifespan,
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(city.router)
app.include_router(hotel.router)
app.include_router(weather.router)
app.include_router(event.router)
app.include_router(flight.router)
app.include_router(ingest.router)
app.include_router(job.router)
app.include_router(pricing_model.router)
app.include_router(example_widget.router)


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
        theme=Theme.DEEP_SPACE,
    )
