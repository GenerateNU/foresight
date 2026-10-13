from foresight.schemas.base import ResponseSchema


class PageResponse[T](ResponseSchema):
    """One page of a list endpoint: the rows plus where they sit in the full set."""

    items: list[T]
    total: int  # rows matching the filters, ignoring limit/offset
    limit: int
    offset: int
