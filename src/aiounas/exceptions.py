"""Exception hierarchy for aiounas."""

from __future__ import annotations


class UnasError(Exception):
    """Base error for all aiounas failures."""


class UnasConnectionError(UnasError):
    """Network / TLS / timeout failure talking to the console."""


class UnasAuthError(UnasError):
    """Authentication failed or the session/key is no longer valid."""


class UnasApiError(UnasError):
    """The API returned an unexpected status or body."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class UnasCapabilityError(UnasError):
    """The active auth method is not permitted to use this endpoint."""


def describe(err: BaseException) -> str:
    """Text for a caught exception that is never empty.

    Several of the failures this library converts carry no message at all:
    ``str(TimeoutError())`` is ``""``. Interpolated as-is, the cause vanishes and
    a timeout reads exactly like every other failure. The type name is the
    least that still tells them apart.
    """
    return str(err) or type(err).__name__
