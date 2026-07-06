class NotFoundError(Exception):
    """Requested entity does not exist. Mapped to HTTP 404."""


class ConflictError(Exception):
    """Entity violates a uniqueness constraint. Mapped to HTTP 409."""
