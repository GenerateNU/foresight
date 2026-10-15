"""Cities: the markets hotels sit in. Weather, events and flights are kept per
city and shared by its hotels."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, status
from pydantic import Field, field_validator

from foresight.routes.helpers import RequestSchema, ResponseSchema, SessionDep
from foresight.services.domain import city as city_service

router = APIRouter(tags=["Cities"])

_NAME = Field(max_length=120, description='e.g. "Dublin"')
_COUNTRY = Field(
    default=None, min_length=2, max_length=2, description='ISO-3166 alpha-2, e.g. "IE"'
)
_TIMEZONE = Field(max_length=64, description='IANA zone, e.g. "Europe/Dublin"')
_LATITUDE = Field(ge=-90, le=90, description="Centre of the market")
_LONGITUDE = Field(ge=-180, le=180, description="Centre of the market")
_IATA = Field(
    default=None, min_length=3, max_length=3, description='IATA airport code, "DUB"'
)
_ICAO = Field(
    default=None, min_length=4, max_length=4, description='ICAO airport code, "EIDW"'
)


def _check_zone(value: str | None) -> str | None:
    if value is not None:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown IANA timezone {value!r}") from None
    return value


class CityRequest(RequestSchema):
    name: str = _NAME
    country: str | None = _COUNTRY
    timezone: str = _TIMEZONE
    latitude: float = _LATITUDE
    longitude: float = _LONGITUDE
    airport_iata: str | None = _IATA
    airport_icao: str | None = _ICAO

    _zone = field_validator("timezone")(_check_zone)


class CityUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, max_length=120)
    country: str | None = _COUNTRY
    timezone: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    airport_iata: str | None = _IATA
    airport_icao: str | None = _ICAO

    _zone = field_validator("timezone")(_check_zone)

    @field_validator("name", "timezone", "latitude", "longitude")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Required columns: omitting them leaves them alone, null can't clear them.
        if value is None:
            raise ValueError("cannot be null")
        return value


class CityResponse(ResponseSchema):
    id: int
    name: str
    slug: str = Field(description="Normalized name; unique")
    country: str | None
    timezone: str
    latitude: float
    longitude: float
    airport_iata: str | None
    airport_icao: str | None


@router.post(
    "/cities", response_model=CityResponse, status_code=status.HTTP_201_CREATED
)
async def create_city(data: CityRequest, session: SessionDep) -> CityResponse:
    """Add a city. Names are unique once normalized ("Dublin" = "dublin")."""
    city = await city_service.create_city(session, **data.model_dump())
    return CityResponse.model_validate(city)


@router.get("/cities", response_model=list[CityResponse])
async def list_cities(session: SessionDep) -> list[CityResponse]:
    """Every city, by name."""
    cities = await city_service.list_cities(session)
    return [CityResponse.model_validate(city) for city in cities]


@router.get("/cities/{city_id}", response_model=CityResponse)
async def get_city(city_id: int, session: SessionDep) -> CityResponse:
    """One city."""
    return CityResponse.model_validate(await city_service.get_city(session, city_id))


@router.patch("/cities/{city_id}", response_model=CityResponse)
async def update_city(
    city_id: int, data: CityUpdateRequest, session: SessionDep
) -> CityResponse:
    """Change the fields sent; omitted fields are left alone."""
    city = await city_service.update_city(
        session, city_id, data.model_dump(exclude_unset=True)
    )
    return CityResponse.model_validate(city)
