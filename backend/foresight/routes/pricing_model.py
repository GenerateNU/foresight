"""Pricing models: train new versions, compare them, choose which one serves.

Training runs as a job on data that's already ingested; it never fetches.
Every run makes a new version, so earlier ones stay for comparison. Poll
`GET /jobs/{id}` for the result; `progress.model_id` is the new version.
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Path, status
from pydantic import Field

from foresight import worker
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    RequestSchema,
    ResponseSchema,
    SessionDep,
    example_body,
    paginate,
)
from foresight.routes.job import JobResponse
from foresight.services import job as job_service
from foresight.services.domain import pricing_model as model_service

router = APIRouter(tags=["Models"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

_DATE_HELP = "YYYY-MM-DD"


class EBMSettings(RequestSchema):
    """EBM settings to try. Leave any out for the library default."""

    interactions: int | None = Field(
        default=None,
        ge=0,
        le=50,
        description="Pairwise terms such as day of week with month; 0 for "
        "none. Library default: 5 x the feature count",
    )
    learning_rate: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Step size per boosting round; smaller learns slower and "
        "smoother. Library default: 0.04",
    )
    max_bins: int | None = Field(
        default=None,
        ge=8,
        le=4096,
        description="Most bins a numeric feature is cut into. Library default: 1024",
    )
    outer_bags: int | None = Field(
        default=None,
        ge=2,
        le=64,
        description="Sub-models averaged; also drives the uncertainty signal. "
        "Library default: 14",
    )
    min_samples_leaf: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="Fewest nights a split may leave on a side. Library default: 4",
    )
    smoothing_rounds: int | None = Field(
        default=None,
        ge=0,
        le=5000,
        description="Early rounds that smooth the learned curves. Library default: 500",
    )


class TrainRequest(RequestSchema):
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="What this version tries, so you can tell versions apart",
        examples=["What this version tries"],
    )
    start: date | None = Field(
        default=None,
        description=f"First night to train on, inclusive. {_DATE_HELP}. "
        "Omit for the first loaded night",
        examples=["2025-01-01"],
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
    settings: EBMSettings = Field(
        default_factory=EBMSettings,
        description="EBM settings to try; omitted ones use the library default",
    )


# One per use, shown as a picker in /docs. The first is the body built from
# the fields (`example_body`), so it matches the schema and its defaults; the
# others change one thing from it. Only the experiment sets settings: they
# change what training does, so the fields carry no example.
_FULL = example_body(TrainRequest)
_TRAIN_EXAMPLES: dict[str, Any] = {
    "window": {"summary": "New model on a window", "value": _FULL},
    "all_nights": {
        "summary": "New model on every loaded night",
        "value": {"description": _FULL["description"], "activate": _FULL["activate"]},
    },
    "experiment": {
        "summary": "Try settings without serving it",
        "value": {**_FULL, "activate": False, "settings": {"interactions": 0}},
    },
}


class PricingModelResponse(ResponseSchema):
    id: int = Field(description="The model's id")
    hotel_id: int = Field(description="The hotel it prices")
    version: int = Field(description="Counts up per hotel, from 1")
    algorithm: str = Field(description="The model type", examples=["ebm"])
    description: str | None = Field(
        description="What this version tries, as given; null if none"
    )
    is_active: bool = Field(description="True for the one version serving the hotel")
    features: list[str] = Field(description="Model inputs, in order")
    metrics: dict[str, Any] = Field(
        description="Scored on the most recent nights, held out from training; "
        "mae and rmse in EUR"
    )
    lib_versions: dict[str, str] = Field(
        description="Library versions it was trained with"
    )
    data_start: date = Field(description="First night trained on, inclusive")
    data_end: date = Field(description="Last night trained on, inclusive")
    trained_at: datetime = Field(description="When it was saved, UTC")


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]
ModelId = Annotated[int, Path(description="The model's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/hotels/{hotel_id}/train",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
async def train_model(
    hotel_id: HotelId,
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
    )
    tasks.add_task(worker.run_job, job.id)
    return JobResponse.model_validate(job)


@router.get(
    "/hotels/{hotel_id}/models", response_model=PageResponse[PricingModelResponse]
)
async def list_models(
    hotel_id: HotelId, session: SessionDep, page: PageDep
) -> PageResponse[PricingModelResponse]:
    """Every version for the hotel, newest first, to compare metrics."""
    models, total = await model_service.list_models(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(PricingModelResponse, models, total, page)


@router.get("/models/{model_id}", response_model=PricingModelResponse)
async def get_model(model_id: ModelId, session: SessionDep) -> PricingModelResponse:
    """One version: what it was trained on and how it scored."""
    return PricingModelResponse.model_validate(
        await model_service.get_model(session, model_id)
    )


@router.post("/models/{model_id}/activate", response_model=PricingModelResponse)
async def activate_model(
    model_id: ModelId, session: SessionDep
) -> PricingModelResponse:
    """Serve this version for its hotel; the previous one stops serving."""
    return PricingModelResponse.model_validate(
        await model_service.activate_model(session, model_id)
    )
