"""Domain errors raised by services and translated to HTTP by the routes layer.

Services describe *what* went wrong; `routes/errors.py` maps each error to a
status code. A `get_x(id)` lookup that finds nothing raises NotFoundError.
"""


class DomainError(Exception):
    """Base for every error a service raises on purpose."""


class NotFoundError(DomainError):
    """Something the operation depends on doesn't exist."""

    def __init__(self, entity: str, entity_id: int | str) -> None:
        super().__init__(f"{entity} {entity_id} not found")
        self.entity = entity
        self.entity_id = entity_id


class ConflictError(DomainError):
    """The write would duplicate something that already exists."""


class InvalidRequestError(DomainError):
    """The request can't be carried out as given, e.g. a hotel lacks the data
    a source needs, or a date window is empty."""


class NotConfiguredError(DomainError):
    """A server-side setting the operation needs (an API key) is missing."""
