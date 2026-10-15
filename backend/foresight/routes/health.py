"""Liveness check."""

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from foresight.routes.helpers import ResponseSchema

router = APIRouter(tags=["Health"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class HealthResponse(ResponseSchema):
    status: Literal["ok"] = Field(description="Always ok while the API is serving")


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Returns ok while the API is serving requests."""
    return HealthResponse(status="ok")
