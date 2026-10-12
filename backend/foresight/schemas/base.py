from pydantic import BaseModel, ConfigDict


class RequestSchema(BaseModel):
    """Base for request bodies. Unknown fields are rejected with a 422."""

    model_config = ConfigDict(extra="forbid")


class ResponseSchema(BaseModel):
    """Base for response bodies. Can be built from an ORM object."""

    model_config = ConfigDict(from_attributes=True)


class ExternalPayload(BaseModel):
    """Base for data from external APIs. Fields we don't model are ignored."""

    model_config = ConfigDict(extra="ignore")
