"""TLS trust in the integration: the setup flow, migration, and the repairs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_unas_rest.aiounas import (
    TlsMode,
    UnasCertificateMismatch,
    UnasConnectionError,
)
from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_CERT_FINGERPRINT,
    CONF_TLS_MODE,
    DOMAIN,
    ISSUE_CERT_MISMATCH,
    ISSUE_TLS_INSECURE,
)
from custom_components.unifi_unas_rest.repairs import async_create_fix_flow
from custom_components.unifi_unas_rest.tls import ssl_for_entry, tls_mode_of
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

_FP = "ab:" * 31 + "ab"
_OTHER_FP = "cd:" * 31 + "cd"
_HOST = {CONF_HOST: "192.0.2.10", CONF_PORT: 443}


# --- migration of entries that predate the setting ----------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_CERT_FINGERPRINT: _FP}, TlsMode.FINGERPRINT),
        ({CONF_TLS_MODE: TlsMode.CA}, TlsMode.CA),
        ({CONF_VERIFY_SSL: True}, TlsMode.CA),
        ({CONF_VERIFY_SSL: False}, TlsMode.INSECURE),
        ({}, TlsMode.INSECURE),
    ],
)
def test_tls_mode_of_reads_old_and_new_entries(stored: dict, expected: TlsMode) -> None:
    """An entry written before pinning existed keeps the behaviour it had.

    ``verify_ssl=False`` becomes INSECURE rather than being upgraded in place:
    pinning whatever the console serves during an upgrade would record a
    certificate the user never saw.
    """
    assert tls_mode_of(stored) is expected


def test_ssl_for_entry_maps_each_mode() -> None:
    assert ssl_for_entry({CONF_TLS_MODE: TlsMode.CA}) is True
    assert ssl_for_entry({CONF_VERIFY_SSL: False}) is False
    pinned = ssl_for_entry({CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_CERT_FINGERPRINT: _FP})
    assert pinned is not True and pinned is not False


# --- config flow: trust on first use ------------------------------------------


async def test_user_flow_pins_the_certificate(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    """The default path: the fingerprint is shown, accepted, and stored."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(return_value=_FP),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "tls_fingerprint"
    assert result["description_placeholders"]["fingerprint"] == _FP

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "api_key"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k123456789"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TLS_MODE] == TlsMode.FINGERPRINT
    assert result["data"][CONF_CERT_FINGERPRINT] == _FP


async def test_user_flow_reports_a_console_it_cannot_read(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(side_effect=UnasConnectionError("down")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_non_pinning_modes_skip_the_fingerprint_step(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """CA and insecure must not stop to show a certificate, or store one."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**_HOST, CONF_TLS_MODE: TlsMode.CA, CONF_AUTH_METHOD: AUTH_API_KEY},
    )
    assert result["step_id"] == "api_key"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k123456789"}
    )
    assert result["data"][CONF_TLS_MODE] == TlsMode.CA
    assert CONF_CERT_FINGERPRINT not in result["data"]


# --- setup: a changed certificate is a repair, never a credential prompt ------


async def test_mismatch_raises_a_repair_and_not_reauth(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """The classification that matters: not ConfigEntryAuthFailed.

    Sending the user to a password form while something may be impersonating
    their console trains exactly the wrong reflex.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            **_HOST,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
            CONF_API_KEY: "k123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
    entry.add_to_hass(hass)
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasCertificateMismatch(_FP, _OTHER_FP))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders["expected"] == _FP
    assert issue.translation_placeholders["got"] == _OTHER_FP
    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]


async def test_an_unverified_entry_is_flagged_and_clears_once_pinned(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The insecure entry keeps working, and is offered the upgrade once."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
        },
    )
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


# --- the repair flows ---------------------------------------------------------


async def test_accepting_a_new_certificate_repins_the_entry(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            **_HOST,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
            CONF_API_KEY: "k123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
    entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass,
        f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}",
        {"entry_id": entry.entry_id, "expected": _FP, "fingerprint": _OTHER_FP},
    )
    flow.hass = hass

    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(return_value=_OTHER_FP),
    ):
        result = await flow.async_step_init()
        assert result["step_id"] == "confirm"
        assert result["description_placeholders"] == {"expected": _FP, "got": _OTHER_FP}

        result = await flow.async_step_confirm({})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_CERT_FINGERPRINT] == _OTHER_FP


async def test_the_insecure_repair_pins_what_the_console_serves(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}", {"entry_id": config_entry.entry_id}
    )
    flow.hass = hass
    # The console is serving the same certificate at both moments, which is the
    # ordinary case: the value shown is the value pinned.
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(return_value=_FP),
    ):
        result = await flow.async_step_init()
        assert result["description_placeholders"]["fingerprint"] == _FP
        result = await flow.async_step_confirm({})
    await hass.async_block_till_done()
    assert config_entry.data[CONF_TLS_MODE] == TlsMode.FINGERPRINT
    assert config_entry.data[CONF_CERT_FINGERPRINT] == _FP


async def test_the_insecure_repair_gives_up_when_the_console_is_unreachable(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}", {"entry_id": config_entry.entry_id}
    )
    flow.hass = hass
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(side_effect=UnasConnectionError("down")),
    ):
        result = await flow.async_step_init()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.parametrize("issue_prefix", [ISSUE_CERT_MISMATCH, ISSUE_TLS_INSECURE])
async def test_a_repair_for_an_entry_that_is_gone_aborts(
    hass: HomeAssistant, issue_prefix: str
) -> None:
    """The entry can be deleted while its repair sits in the notification list."""
    flow = await async_create_fix_flow(
        hass, f"{issue_prefix}_missing", {"entry_id": "missing", "fingerprint": _FP}
    )
    flow.hass = hass
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(return_value=_FP),
    ):
        result = await flow.async_step_init()
        if result["type"] is not FlowResultType.ABORT:
            result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


async def test_setup_flow_surfaces_a_mismatch_as_its_own_error(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """During setup a swapped certificate must not read as a bad credential."""
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasCertificateMismatch(_FP, _OTHER_FP))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**_HOST, CONF_TLS_MODE: TlsMode.INSECURE, CONF_AUTH_METHOD: AUTH_API_KEY},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k123456789"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cert_mismatch"}


async def test_reauth_surfaces_a_mismatch_as_its_own_error(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """And so must reauth, which is where the wrong answer is most tempting."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasCertificateMismatch(_FP, _OTHER_FP))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k987654321"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cert_mismatch"}


async def test_a_certificate_that_changes_while_running_also_raises_the_repair(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A swap after setup must reach the user the same way as one before it.

    ``UnasCertificateMismatch`` is a ``UnasConnectionError``, so the coordinator's
    ordinary branch would turn it into a plain ``UpdateFailed``: the entities go
    unavailable and the reason stays buried in the log.
    """
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    mock_aiounas.get_storage = AsyncMock(side_effect=UnasCertificateMismatch(_FP, _OTHER_FP))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["got"] == _OTHER_FP
    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]


async def test_reconfigure_says_when_the_certificate_is_not_the_stored_one(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """Reconfigure must not re-pin silently.

    Someone opening reconfigure to change an API key while their console is being
    impersonated would otherwise accept a stranger's certificate with nothing on
    screen to notice.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            **_HOST,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
            CONF_API_KEY: "k123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(return_value=_OTHER_FP),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "tls_fingerprint_changed"
    assert result["description_placeholders"]["previous"] == _FP
    assert result["description_placeholders"]["fingerprint"] == _OTHER_FP

    # And accepting it stores the new certificate rather than the old one.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "api_key"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k123456789"}
    )
    await hass.async_block_till_done()
    assert entry.data[CONF_CERT_FINGERPRINT] == _OTHER_FP


async def test_reconfigure_is_quiet_when_the_certificate_is_unchanged(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """The other half: an unchanged certificate must not raise an alarm."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            **_HOST,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
            CONF_API_KEY: "k123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(return_value=_FP),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "tls_fingerprint"


async def test_the_insecure_repair_will_not_pin_a_certificate_that_moved(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Both rules at once, and they pull in opposite directions.

    Pin only what was shown — so confirmation cannot store a second reading. And
    never pin what is no longer served — so it cannot store the first one either
    once the console has moved on. A repair can sit unread for days; the answer
    is to show the new value and wait for the user again.
    """
    config_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}", {"entry_id": config_entry.entry_id}
    )
    flow.hass = hass
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(side_effect=[_FP, _OTHER_FP]),
    ):
        result = await flow.async_step_init()
        assert result["description_placeholders"]["fingerprint"] == _FP
        result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.FORM, "a moved certificate must be shown, not pinned"
    assert result["description_placeholders"]["fingerprint"] == _OTHER_FP
    assert config_entry.data[CONF_TLS_MODE] == TlsMode.INSECURE
    assert CONF_CERT_FINGERPRINT not in config_entry.data


async def test_the_mismatch_repair_will_not_pin_a_certificate_that_moved(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Same rule for the notification raised by a mismatch.

    Its fingerprint was recorded when the mismatch happened, which may be days
    before anyone presses the button.
    """
    config_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass,
        f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}",
        {"entry_id": config_entry.entry_id, "expected": _FP, "fingerprint": _OTHER_FP},
    )
    flow.hass = hass
    third = "ef:" * 31 + "ef"
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(return_value=third),
    ):
        result = await flow.async_step_init()
        assert result["description_placeholders"]["got"] == _OTHER_FP
        result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["got"] == third
    assert config_entry.data.get(CONF_CERT_FINGERPRINT) is None


async def test_a_recovered_console_withdraws_the_certificate_repair(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The repair must not outlive the condition it reports.

    Otherwise a healthy system carries an alarming notification, and pressing its
    button would pin a certificate the console no longer serves.
    """
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data.coordinator
    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}"

    storage = mock_aiounas.get_storage
    mock_aiounas.get_storage = AsyncMock(side_effect=UnasCertificateMismatch(_FP, _OTHER_FP))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    mock_aiounas.get_storage = storage
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_the_mismatch_repair_gives_up_when_the_console_is_unreachable(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """It cannot confirm what is being served, so it must not pin anything."""
    config_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass,
        f"{ISSUE_CERT_MISMATCH}_{config_entry.entry_id}",
        {"entry_id": config_entry.entry_id, "expected": _FP, "fingerprint": _OTHER_FP},
    )
    flow.hass = hass
    with patch(
        "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
        AsyncMock(side_effect=UnasConnectionError("down")),
    ):
        await flow.async_step_init()
        result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert config_entry.data.get(CONF_CERT_FINGERPRINT) is None


# --- how the two failures are reported ----------------------------------------


def test_a_swapped_certificate_is_not_reported_as_unreachable() -> None:
    """A control action refused over TLS must say what actually happened.

    ``UnasCertificateMismatch`` is a ``UnasConnectionError``, so it fell into the
    "could not reach the UNAS" branch — which sends the user to check cables and
    firewalls and hides the one thing they need to look at. The console is
    reachable; it is presenting a different certificate.
    """
    from custom_components.unifi_unas_rest.errors import action_error

    err = action_error(UnasCertificateMismatch(_FP, _OTHER_FP))
    assert err.translation_key == "cert_mismatch"
    assert err.translation_placeholders == {"expected": _FP, "got": _OTHER_FP}


def test_an_ordinary_connection_failure_still_reads_as_one() -> None:
    """The other direction: the new branch must not swallow real outages."""
    from custom_components.unifi_unas_rest.errors import action_error

    assert action_error(UnasConnectionError("down")).translation_key == "cannot_connect"


async def test_an_unreachable_console_returns_to_the_step_the_user_is_on(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """Reconfigure must not drop the user into the first-time setup form.

    Both steps collect the same fields, so the only signal that something went
    wrong is the step id — and landing on `user` makes it look as though the
    existing entry was lost.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            **_HOST,
            CONF_TLS_MODE: TlsMode.FINGERPRINT,
            CONF_CERT_FINGERPRINT: _FP,
            CONF_API_KEY: "k123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(side_effect=UnasConnectionError("down")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_first_time_setup_still_returns_to_the_user_step(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """And a fresh install must keep landing on `user`, not on `reconfigure`."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(
        "custom_components.unifi_unas_rest.config_flow.async_probe_fingerprint",
        AsyncMock(side_effect=UnasConnectionError("down")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_HOST, CONF_TLS_MODE: TlsMode.FINGERPRINT, CONF_AUTH_METHOD: AUTH_API_KEY},
        )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
