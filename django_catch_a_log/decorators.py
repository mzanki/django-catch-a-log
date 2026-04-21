import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from .cid import generate_new_cid, reset_cid, set_cid


logger = logging.getLogger(__name__)


def _resolve_cid(func: Callable, kwargs: dict) -> str:
    cid = kwargs.pop("cid", None)
    if not cid:
        cid = generate_new_cid()
        logger.debug(f"No cid provided to '{func.__name__}'. Generated new: {cid}")
    return cid


def with_correlation_id(func: Callable) -> Callable:
    """
    Decorator to ensure that a correlation ID (cid) is set in the context for the desired function.
    If a cid is not provided in the function's kwargs, a new one will be generated and set.
    Resets the CID after the wrapped call returns to avoid leaking across tasks on a shared worker.
    Supports both sync and async functions.
    """

    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            cid = _resolve_cid(func, kwargs)
            token = set_cid(cid)
            try:
                return await func(*args, **kwargs)
            finally:
                reset_cid(token)

        return async_wrapper

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        cid = _resolve_cid(func, kwargs)
        token = set_cid(cid)
        try:
            return func(*args, **kwargs)
        finally:
            reset_cid(token)

    return wrapper
