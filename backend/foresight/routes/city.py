from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Path, status
from pydantic import Field, field_validator

from foresight.routes.access import EditableCityId
from foresight.routes.helpers import RequestSchema, ResponseSchema, SessionDep
from foresight.services.hotels import city as city_service

router = APIRouter(tags=["Cities"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

_NAME: dict[str, Any] = {
    "max_length": 120,
    "description": "The city's name; unique once normalized",
    "examples": ["Example City"],
}
_COUNTRY: dict[str, Any] = {
    "min_length": 2,
    "max_length": 2,
    "description": "ISO-3166 alpha-2 country code",
    "examples": ["XX"],
}
_TIMEZONE: dict[str, Any] = {
    "max_length": 64,
    "description": "IANA timezone; stay nights are local to it",
    "examples": ["UTC"],
}
_LATITUDE: dict[str, Any] = {
    "ge": -90,
    "le": 90,
    "description": "Centre of the market, in degrees; north is positive",
    "examples": [12.34],
}
_LONGITUDE: dict[str, Any] = {
    "ge": -180,
    "le": 180,
    "description": "Centre of the market, in degrees; east is positive, west negative",
    "examples": [-56.78],
}


def _check_zone(value: str | None) -> str | None:
    """Checks a timezone is a known IANA name.

    Args:
        value (str | None): The timezone.

    Returns:
        str | None: The timezone.

    Raises:
        ValueError: It isn't known.
    """
    if value is not None:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown IANA timezone {value!r}") from None
    return value


class CityRequest(RequestSchema):
    """A new city: a market hotels sit in, whose events its hotels share."""

    name: str = Field(**_NAME)
    country: str | None = Field(default=None, **_COUNTRY)
    timezone: str = Field(**_TIMEZONE)
    latitude: float = Field(**_LATITUDE)
    longitude: float = Field(**_LONGITUDE)

    _zone = field_validator("timezone")(_check_zone)


class CityUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, **_NAME)
    country: str | None = Field(default=None, **_COUNTRY)
    timezone: str | None = Field(default=None, **_TIMEZONE)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)

    _zone = field_validator("timezone")(_check_zone)

    @field_validator("name", "timezone", "latitude", "longitude")
    @classmethod
    def _not_null(cls, value: object) -> object:
        """Rejects null for a required column; leaving it out leaves it alone.

        Args:
            value (object): The value sent.

        Returns:
            object: The value.

        Raises:
            ValueError: It's null.
        """
        if value is None:
            raise ValueError("cannot be null")
        return value


class CityResponse(ResponseSchema):
    """A city: a market hotels sit in, whose events its hotels share."""

    id: int = Field(description="The city's id")
    name: str = Field(description="The city's name")
    slug: str = Field(description="Normalized name; unique")
    country: str | None = Field(description="ISO-3166 alpha-2 code; null if unset")
    timezone: str = Field(description="IANA timezone; stay nights are local to it")
    latitude: float = Field(description="Centre of the market, in degrees")
    longitude: float = Field(description="Centre of the market, in degrees")


CityId = Annotated[int, Path(description="The city's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/cities", response_model=CityResponse, status_code=status.HTTP_201_CREATED
)
async def create_city(data: CityRequest, session: SessionDep) -> CityResponse:
    """Add a city. Names are unique once normalized ("Example" = "example").

    \f
    Args:
        data (CityRequest): The city.
        session (SessionDep): The database session.

    Returns:
        CityResponse: The new city.

    Raises:
        ConflictError: A city with the same normalized name exists.
    """
    city = await city_service.create_city(session, **data.model_dump())
    return CityResponse.model_validate(city)


@router.get("/cities", response_model=list[CityResponse])
async def list_cities(session: SessionDep) -> list[CityResponse]:
    """Every city, by name.

    \f
    Args:
        session (SessionDep): The database session.

    Returns:
        list[CityResponse]: The cities.
    """
    cities = await city_service.list_cities(session)
    return [CityResponse.model_validate(city) for city in cities]


@router.get("/cities/{city_id}", response_model=CityResponse)
async def get_city(city_id: CityId, session: SessionDep) -> CityResponse:
    """One city.

    \f
    Args:
        city_id (CityId): The city.
        session (SessionDep): The database session.

    Returns:
        CityResponse: The city.

    Raises:
        NotFoundError: The city doesn't exist.
    """
    return CityResponse.model_validate(await city_service.get_city(session, city_id))


@router.patch("/cities/{city_id}", response_model=CityResponse)
async def update_city(
    city_id: EditableCityId, data: CityUpdateRequest, session: SessionDep
) -> CityResponse:
    """Change the fields sent; omitted fields are left alone.

    Only people linked to a hotel in the city can: every hotel there shares
    it.

    \f
    Args:
        city_id (EditableCityId): The city.
        data (CityUpdateRequest): The changes.
        session (SessionDep): The database session.

    Returns:
        CityResponse: The updated city.

    Raises:
        ConflictError: The new name normalizes to another city's.
    """
    city = await city_service.update_city(
        session, city_id, data.model_dump(exclude_unset=True)
    )
    return CityResponse.model_validate(city)
