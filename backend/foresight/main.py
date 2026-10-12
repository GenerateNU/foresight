from fastapi import FastAPI
from scalar_fastapi import Theme, get_scalar_api_reference

from foresight.config import settings
from foresight.routes import example_widget, health

app = FastAPI(
    title=settings.app_name,
    description="AI revenue intelligence platform for boutique hotels",
    version="0.1.0",
    # Use Scalar for the API reference instead of the built-in Swagger UI.
    docs_url=None,
)

app.include_router(health.router)
app.include_router(example_widget.router)


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
        theme=Theme.DEEP_SPACE,
    )
