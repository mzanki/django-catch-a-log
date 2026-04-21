import uuid
from contextvars import ContextVar, Token


NO_CID_DISPLAY = "---"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def generate_new_cid() -> str:
    """Generates and returns a new unique correlation ID."""
    return str(uuid.uuid4())


def set_cid(cid: str) -> Token:
    """Sets the correlation ID for the current context. Returns a token usable with reset_cid."""
    return _correlation_id.set(cid)


def reset_cid(token: Token) -> None:
    """Resets the correlation ID to the value it had before the matching set_cid call."""
    _correlation_id.reset(token)


def get_cid() -> str | None:
    """Retrieves the correlation ID from the current context."""
    return _correlation_id.get()
