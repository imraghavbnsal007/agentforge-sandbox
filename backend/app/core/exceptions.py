class NotFoundError(Exception):
    """Requested entity does not exist. Mapped to HTTP 404."""


class ConflictError(Exception):
    """Entity violates a uniqueness or state constraint. Mapped to HTTP 409."""


class InvalidInputError(Exception):
    """Input failed validation beyond schema checks. Mapped to HTTP 422."""


class ForbiddenError(Exception):
    """Action refused by policy (e.g. repo allowlist). Mapped to HTTP 403."""
