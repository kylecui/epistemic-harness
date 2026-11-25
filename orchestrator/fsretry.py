"""Transient filesystem failures from the container's file-sharing layer (issue #24).

Docker Desktop's bind mounts return ENOMEM / EIO / ESTALE under load while the same paths work a
moment later, and the error surfaces as a bare OSError mid-dispatch. Retrying once and naming the
remedy is honest; retrying forever would hide a broken host.
"""
from __future__ import annotations

import errno
import time
from typing import Callable, TypeVar

TRANSIENT_ERRNOS = frozenset({errno.ENOMEM, errno.EIO, errno.EBUSY,
                              getattr(errno, "ESTALE", 116)})
REMEDY = ("the docker VM's file sharing looks unhealthy; retry the call, and if it keeps failing "
          "restart Docker Desktop")
T = TypeVar("T")


class MountUnhealthy(RuntimeError):
    """Raised after the retry budget is spent on a transient filesystem error."""


def is_transient(exc: BaseException) -> bool:
    """ENOENT/ENOTDIR stay fatal: a genuinely missing path must not be retried into a timeout."""
    return isinstance(exc, OSError) and exc.errno in TRANSIENT_ERRNOS


def with_retry(fn: Callable[[], T], *, attempts: int = 2, delay: float = 1.5) -> T:
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except OSError as exc:
            if not is_transient(exc):
                raise
            last = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise MountUnhealthy(f"{last} — {REMEDY}") from last
