"""Cities: the markets hotels sit in. Weather, events and flights are kept per
city and shared by its hotels."""

from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Path, status
from pydantic import Field, field_validator

from foresight.routes.helpers import RequestSchema, ResponseSchema, SessionDep
from foresight.services.domain import city as city_service

router = APIRouter(tags=["Cities"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

# Field settings shared by the create and update bodies.
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
_IATA: dict[str, Any] = {
    "min_length": 3,
    "max_length": 3,
    "description": "IATA code of the city's main airport",
    "examples": ["XXX"],
}
_ICAO: dict[str, Any] = {
    "min_length": 4,
    "max_length": 4,
    "description": "ICAO code of the city's main airport",
    "examples": ["XXXX"],
}


def _check_zone(value: str | None) -> str | None:
    if value is not None:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown IANA timezone {value!r}") from None
    return value


class CityRequest(RequestSchema):
    name: str = Field(**_NAME)
    country: str | None = Field(default=None, **_COUNTRY)
    timezone: str = Field(**_TIMEZONE)
    latitude: float = Field(**_LATITUDE)
    longitude: float = Field(**_LONGITUDE)
    airport_iata: str | None = Field(default=None, **_IATA)
    airport_icao: str | None = Field(default=None, **_ICAO)

    _zone = field_validator("timezone")(_check_zone)


class CityUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, **_NAME)
    country: str | None = Field(default=None, **_COUNTRY)
    timezone: str | None = Field(default=None, **_TIMEZONE)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)
    airport_iata: str | None = Field(default=None, **_IATA)
    airport_icao: str | None = Field(default=None, **_ICAO)

    _zone = field_validator("timezone")(_check_zone)

    @field_validator("name", "timezone", "latitude", "longitude")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Required columns: omitting them leaves them alone, null can't clear them.
        if value is None:
            raise ValueError("cannot be null")
        return value


class CityResponse(ResponseSchema):
    id: int = Field(description="The city's id")
    name: str = Field(description="The city's name")
    slug: str = Field(description="Normalized name; unique")
    country: str | None = Field(description="ISO-3166 alpha-2 code; null if unset")
    timezone: str = Field(description="IANA timezone; stay nights are local to it")
    latitude: float = Field(description="Centre of the market, in degrees")
    longitude: float = Field(description="Centre of the market, in degrees")
    airport_iata: str | None = Field(description="Main airport's IATA code")
    airport_icao: str | None = Field(description="Main airport's ICAO code")


CityId = Annotated[int, Path(description="The city's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/cities", response_model=CityResponse, status_code=status.HTTP_201_CREATED
)
async def create_city(data: CityRequest, session: SessionDep) -> CityResponse:
    """Add a city. Names are unique once normalized ("Example" = "example")."""
    city = await city_service.create_city(session, **data.model_dump())
    return CityResponse.model_validate(city)


@router.get("/cities", response_model=list[CityResponse])
async def list_cities(session: SessionDep) -> list[CityResponse]:
    """Every city, by name."""
    cities = await city_service.list_cities(session)
    return [CityResponse.model_validate(city) for city in cities]


@router.get("/cities/{city_id}", response_model=CityResponse)
async def get_city(city_id: CityId, session: SessionDep) -> CityResponse:
    """One city."""
    return CityResponse.model_validate(await city_service.get_city(session, city_id))


@router.patch("/cities/{city_id}", response_model=CityResponse)
async def update_city(
    city_id: CityId, data: CityUpdateRequest, session: SessionDep
) -> CityResponse:
    """Change the fields sent; omitted fields are left alone."""
    city = await city_service.update_city(
        session, city_id, data.model_dump(exclude_unset=True)
    )
    return CityResponse.model_validate(city)
