from fastapi import FastAPI

from config import settings
from routes import health

app = FastAPI(
    title=settings.app_name,
    description="AI revenue intelligence platform for boutique hotels",
    version="0.1.0",
)

app.include_router(health.router)
