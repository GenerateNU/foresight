"""Pricing models: train new versions, compare them, choose which one serves.

Training runs as a job on data that's already ingested; it never fetches.
Every run makes a new version, so earlier ones stay for comparison. Poll
`GET /jobs/{id}` for the result; `progress.model_id` is the new version.
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, status
from pydantic import ConfigDict, Field

from foresight import worker
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    RequestSchema,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.routes.job import JobResponse
from foresight.services import job as job_service
from foresight.services.domain import pricing_model as model_service

router = APIRouter(tags=["Models"])


# --- schemas ----------------------------------------------------------------

_DATE_HELP = "ISO 8601 date, YYYY-MM-DD"


class EBMSettings(RequestSchema):
    """EBM settings to try. Leave any out for the library default."""

    interactions: int | None = Field(
        default=None,
        ge=0,
        le=50,
        description="Pairwise terms like 'day_of_week & month'; 0 for none",
    )
    learning_rate: float | None = Field(default=None, gt=0, le=1)
    max_bins: int | None = Field(default=None, ge=8, le=4096)
    outer_bags: int | None = Field(
        default=None,
        ge=2,
        le=64,
        description="Sub-models averaged; also drives the uncertainty signal",
    )
    min_samples_leaf: int | None = Field(default=None, ge=1, le=500)
    smoothing_rounds: int | None = Field(default=None, ge=0, le=5000)


class TrainRequest(RequestSchema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "description": "Baseline: 2022-2025 nights, recorded weather",
                    "start": "2022-01-01",
                    "end": "2025-12-31",
                }
            ]
        }
    )

    description: str | None = Field(
        default=None,
        max_length=2000,
        description="What this version tries, so you can tell versions apart",
        examples=["Baseline: 2022-2025 nights, recorded weather"],
    )
    start: date | None = Field(
        default=None,
        description=f"First night to train on, inclusive. {_DATE_HELP}. "
        "Omit for the first loaded night",
        examples=["2022-01-01"],
    )
    end: date | None = Field(
        default=None,
        description=f"Last night to train on, inclusive. {_DATE_HELP}. "
        "Omit for the last loaded night",
        examples=["2025-12-31"],
    )
    activate: bool = Field(
        default=True,
        description="Serve this version once trained. False keeps the current "
        "one serving, to compare first",
    )
    settings: EBMSettings = Field(default_factory=EBMSettings)
    copy_settings_from: int | None = Field(
        default=None,
        description="Retrain with an earlier version's settings and window; "
        "anything sent here overrides them",
    )


_TRAIN_EXAMPLES: dict[str, Any] = {
    "baseline": {
        "summary": "New model on every loaded night",
        "value": {"description": "Baseline: every night, recorded weather"},
    },
    "window": {
        "summary": "New model on a window",
        "value": {
            "description": "2023 onwards only",
            "start": "2023-01-01",
            "end": "2025-12-31",
        },
    },
    "experiment": {
        "summary": "Try settings without serving it",
        "value": {
            "description": "No interaction terms",
            "activate": False,
            "settings": {"interactions": 0},
        },
    },
    "retrain": {
        "summary": "Retrain an earlier version's setup",
        "value": {"description": "v1 retrained on new nights", "copy_settings_from": 1},
    },
}


class PricingModelResponse(ResponseSchema):
    id: int
    hotel_id: int
    version: int
    algorithm: str
    description: str | None
    is_active: bool
    features: list[str]
    metrics: dict[str, Any] = Field(
        description="Scored on the most recent nights, held out from training"
    )
    training_summary: dict[str, Any] = Field(
        description="Nights used and excluded, settings, which signals had data"
    )
    lib_versions: dict[str, str]
    data_start: date
    data_end: date
    trained_at: datetime


# --- endpoints --------------------------------------------------------------


@router.post(
    "/hotels/{hotel_id}/train",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
async def train_model(
    hotel_id: int,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: Annotated[TrainRequest | None, Body(openapi_examples=_TRAIN_EXAMPLES)] = None,
) -> JobResponse:
    """Train a new version on the hotel's ingested performance and weather.

    Ingest first; this never fetches. Fails fast (422) if no nights are
    loaded in the window.
    """
    data = data or TrainRequest()
    job = await job_service.start_train_job(
        session,
        hotel_id,
        description=data.description,
        start=data.start,
        end=data.end,
        activate=data.activate,
        ebm_params=data.settings.model_dump(exclude_none=True),
        copy_settings_from=data.copy_settings_from,
    )
    tasks.add_task(worker.run_job, job.id)
    return JobResponse.model_validate(job)


@router.get(
    "/hotels/{hotel_id}/models", response_model=PageResponse[PricingModelResponse]
)
async def list_models(
    hotel_id: int, session: SessionDep, page: PageDep
) -> PageResponse[PricingModelResponse]:
    """Every version for the hotel, newest first, to compare metrics."""
    models, total = await model_service.list_models(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(PricingModelResponse, models, total, page)


@router.get("/models/{model_id}", response_model=PricingModelResponse)
async def get_model(model_id: int, session: SessionDep) -> PricingModelResponse:
    """One version: what it was trained on and how it scored."""
    return PricingModelResponse.model_validate(
        await model_service.get_model(session, model_id)
    )


@router.post("/models/{model_id}/activate", response_model=PricingModelResponse)
async def activate_model(model_id: int, session: SessionDep) -> PricingModelResponse:
    """Serve this version for its hotel; the previous one stops serving."""
    return PricingModelResponse.model_validate(
        await model_service.activate_model(session, model_id)
    )
