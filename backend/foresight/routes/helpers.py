from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def example_body(model: type[BaseModel]) -> dict[str, Any]:
    """Builds a request body from each field's default, else its example.

    Nested bodies are built the same way. Fields with neither are left out, so
    a field whose value changes behaviour (an id to copy from) has no example.
    A default always wins, so the body /docs shows does what sending nothing
    would do for those fields.

    Args:
        model (type[BaseModel]): The request schema.

    Returns:
        dict[str, Any]: The example body.
    """
    body: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        nested = field.annotation
        if field.default not in (None, PydanticUndefined):
            body[name] = field.default
        elif isinstance(nested, type) and issubclass(nested, BaseModel):
            body[name] = example_body(nested)
        elif field.examples:
            body[name] = field.examples[0]
    return body


def _add_example_body(schema: dict[str, Any], model: type[BaseModel]) -> None:
    """Adds the body built by `example_body` to a schema's JSON schema.

    Args:
        schema (dict[str, Any]): The JSON schema, changed in place.
        model (type[BaseModel]): The request schema.
    """
    schema["examples"] = [example_body(model)]


class RequestSchema(BaseModel):
    """Base for request bodies.

    Unknown fields are rejected with a 422, and /docs shows a body built from
    the fields' examples.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_add_example_body)


class ResponseSchema(BaseModel):
    """Base for response bodies. Can be built from an ORM object or dataclass."""

    model_config = ConfigDict(from_attributes=True)


class PageResponse[T](ResponseSchema):
    """One page of a list endpoint: the rows plus where they sit in the full set."""

    items: list[T] = Field(description="This page's rows")
    total: int = Field(description="Rows matching the filters, ignoring limit/offset")
    limit: int = Field(description="Page size used")
    offset: int = Field(description="Rows skipped before this page")


@dataclass
class Pagination:
    """`?limit=&offset=` query params for lists that can grow without bound.

    Attributes:
        limit (int): Rows per page.
        offset (int): Rows to skip.
    """

    limit: Annotated[int, Query(ge=1, le=200, description="Rows per page")] = 50
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0


PageDep = Annotated[Pagination, Depends()]


def paginate[T: ResponseSchema](
    schema: type[T], rows: Sequence[Any], total: int, page: Pagination
) -> PageResponse[T]:
    """Maps rows to a response schema and wraps them in the page envelope.

    Args:
        schema (type[T]): The response schema for one row.
        rows (Sequence[Any]): This page's ORM rows or dataclasses.
        total (int): Rows matching the filters, ignoring limit and offset.
        page (Pagination): The page asked for.

    Returns:
        PageResponse[T]: The page.
    """
    return PageResponse(
        items=[schema.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
