"""Exception hierarchy tests."""

from __future__ import annotations

import pytest

from aiounas.exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasConnectionError,
    UnasError,
)


def test_subclasses_of_base() -> None:
    assert issubclass(UnasAuthError, UnasError)
    assert issubclass(UnasConnectionError, UnasError)
    assert issubclass(UnasApiError, UnasError)


def test_error_carries_message() -> None:
    with pytest.raises(UnasError, match="boom"):
        raise UnasAuthError("boom")


def test_api_error_carries_status() -> None:
    err = UnasApiError("bad", status=500)
    assert err.status == 500
