"""Liveness check."""

from typing import Literal

from fastapi import APIRouter

from foresight.routes.helpers import ResponseSchema

router = APIRouter(tags=["health"])


class HealthResponse(ResponseSchema):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Returns ok while the API is serving requests."""
    return HealthResponse(status="ok")
