class DomainError(Exception):
    """Base for every error a service raises on purpose.

    Services say what went wrong; `routes/errors.py` maps each error to a
    status code.
    """


class NotFoundError(DomainError):
    """Something the operation depends on doesn't exist.

    Attributes:
        entity (str): What was looked for, e.g. "Hotel".
        entity_id (int | str): The id that wasn't found.
    """

    entity: str
    entity_id: int | str

    def __init__(self, entity: str, entity_id: int | str) -> None:
        """Builds the error's message from what was looked for.

        Args:
            entity (str): What was looked for, e.g. "Hotel".
            entity_id (int | str): The id that wasn't found.
        """
        super().__init__(f"{entity} {entity_id} not found")
        self.entity = entity
        self.entity_id = entity_id


class ConflictError(DomainError):
    """The write would duplicate something that already exists."""


class InvalidRequestError(DomainError):
    """The request can't be carried out as given, e.g. an empty date window."""


class NotConfiguredError(DomainError):
    """A server setting the operation needs, such as an API key, is missing."""


class NotSignedInError(DomainError):
    """The caller has no valid session.

    None was sent, it expired, or its user no longer exists.
    """


class ForbiddenError(DomainError):
    """The caller is known but isn't allowed to do this.

    For example, a Google account whose email Google hasn't verified.
    """
