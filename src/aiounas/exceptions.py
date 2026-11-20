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


class UnasOperationBlocked(UnasApiError):
    """The console refused a write because a critical operation is running.

    UniFi OS answers ``409`` with code ``CRITICAL_OPERATION_IN_PROGRESS`` and the
    operations in the way (for example a RAID rebuild or a firmware install)
    when a reboot, power-off or update would interrupt them. The console offers
    an override; this library never sends it, so the refusal is final.
    """

    def __init__(self, path: str, blockers: tuple[str, ...]) -> None:
        listed = "; ".join(blockers) or "not described"
        super().__init__(
            f"{path} refused: a critical operation is in progress ({listed})", status=409
        )
        self.blockers = blockers


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
