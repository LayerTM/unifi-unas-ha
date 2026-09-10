"""TLS trust: fingerprint parsing, and pinning against a real handshake.

The pinning tests deliberately do not mock aiohttp. A self-signed certificate is
generated, a TLS server is started with it, and the client is pointed at it —
once with the right fingerprint and once with the wrong one. Mocking the check
would only prove the mock was called; this proves the connection is refused.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import ssl
from collections.abc import AsyncIterator

import aiohttp
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from aiounas.tls import (
    TlsMode,
    UnasCertificateMismatch,
    async_probe_fingerprint,
    format_fingerprint,
    mismatch_from,
    parse_fingerprint,
    ssl_param,
)

_OTHER = "aa:" * 31 + "aa"


def _self_signed(tmp_path, common_name: str = "localhost") -> tuple[str, str, str]:
    """Write a self-signed cert/key pair; return (cert_path, key_path, sha256)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{common_name}.pem"
    key_path = tmp_path / f"{common_name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()
    return str(cert_path), str(key_path), format_fingerprint(digest)


class _Server:
    def __init__(self, port: int, fingerprint: str) -> None:
        self.port = port
        self.fingerprint = fingerprint


@pytest.fixture
async def tls_server(tmp_path) -> AsyncIterator[_Server]:
    """A minimal HTTPS server presenting a freshly generated self-signed cert."""
    cert_path, key_path, fingerprint = _self_signed(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    async with server:
        await server.start_serving()
        yield _Server(port, fingerprint)


# --- fingerprint parsing ------------------------------------------------------


def test_parse_accepts_the_shapes_people_paste() -> None:
    digest = hashlib.sha256(b"cert").digest()
    canonical = format_fingerprint(digest)
    assert parse_fingerprint(canonical) == digest
    assert parse_fingerprint(canonical.upper()) == digest
    assert parse_fingerprint(canonical.replace(":", "")) == digest
    assert parse_fingerprint(canonical.replace(":", "-")) == digest
    assert parse_fingerprint(f"  {canonical}  ") == digest


@pytest.mark.parametrize("value", ["", "zz", "ab:cd", "ab" * 33])
def test_parse_rejects_anything_that_is_not_a_sha256(value: str) -> None:
    with pytest.raises(ValueError):
        parse_fingerprint(value)


def test_ssl_param_per_mode() -> None:
    assert ssl_param(TlsMode.CA) is True
    assert ssl_param(TlsMode.INSECURE) is False
    assert isinstance(ssl_param(TlsMode.FINGERPRINT, _OTHER), aiohttp.Fingerprint)


def test_ssl_param_refuses_to_pin_nothing() -> None:
    """A pinning mode without a pin must fail, never fall back to unverified."""
    with pytest.raises(ValueError):
        ssl_param(TlsMode.FINGERPRINT, None)


def test_mismatch_from_carries_both_fingerprints() -> None:
    expected, got = hashlib.sha256(b"a").digest(), hashlib.sha256(b"b").digest()
    err = mismatch_from(aiohttp.ServerFingerprintMismatch(expected, got, "h", 443))
    assert err.expected == format_fingerprint(expected)
    assert err.got == format_fingerprint(got)
    assert isinstance(err, UnasCertificateMismatch)


# --- against a real handshake -------------------------------------------------


async def test_probe_reads_the_served_certificate(tls_server: _Server) -> None:
    assert await async_probe_fingerprint("127.0.0.1", tls_server.port) == tls_server.fingerprint


async def test_probe_reports_an_unreachable_host() -> None:
    from aiounas.exceptions import UnasConnectionError

    with pytest.raises(UnasConnectionError):
        await async_probe_fingerprint("127.0.0.1", 1, timeout=2)


async def test_matching_fingerprint_connects(tls_server: _Server) -> None:
    """The branch that must succeed: the pinned certificate is the served one."""
    async with (
        aiohttp.ClientSession() as session,
        session.get(
            f"https://127.0.0.1:{tls_server.port}/",
            ssl=ssl_param(TlsMode.FINGERPRINT, tls_server.fingerprint),
        ) as resp,
    ):
        assert resp.status == 200


async def test_mismatched_fingerprint_is_refused(tls_server: _Server) -> None:
    """The branch that must fail, and fail as a mismatch rather than a timeout."""
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ServerFingerprintMismatch) as caught:
            await session.get(
                f"https://127.0.0.1:{tls_server.port}/",
                ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
            )
    assert format_fingerprint(caught.value.got) == tls_server.fingerprint


async def test_ca_mode_rejects_a_self_signed_certificate(tls_server: _Server) -> None:
    """CA mode is a real setting, not a synonym for the pinning one."""
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientConnectorCertificateError):
            await session.get(f"https://127.0.0.1:{tls_server.port}/", ssl=ssl_param(TlsMode.CA))


async def test_insecure_mode_accepts_it(tls_server: _Server) -> None:
    async with (
        aiohttp.ClientSession() as session,
        session.get(
            f"https://127.0.0.1:{tls_server.port}/", ssl=ssl_param(TlsMode.INSECURE)
        ) as resp,
    ):
        assert resp.status == 200


# --- the classification that the auth path used to get wrong -------------------


async def test_client_reports_a_mismatch_as_a_certificate_error(tls_server: _Server) -> None:
    """Through the whole client, a swapped certificate stays a certificate error.

    ``ServerFingerprintMismatch`` is an ``aiohttp.ClientError``, so every handler
    that catches one can swallow it. The read path used to turn it into a plain
    connection error, which loses the fingerprints the user needs.
    """
    from aiounas import ApiKeyAuth, UnasClient

    async with aiohttp.ClientSession() as session:
        client = UnasClient(
            session,
            "127.0.0.1",
            ApiKeyAuth("k"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
        )
        with pytest.raises(UnasCertificateMismatch) as caught:
            await client.get_identity()
    assert caught.value.got == tls_server.fingerprint
    assert caught.value.expected == _OTHER


async def test_session_login_does_not_call_a_swapped_certificate_bad_credentials(
    tls_server: _Server,
) -> None:
    """The expensive misfiling: a mismatch during login is not an auth failure.

    ``SessionAuth._login`` wraps ``aiohttp.ClientError`` into ``UnasAuthError``,
    which Home Assistant treats as terminal — it would tear the entry down and
    ask the user to retype a password that was never wrong, at exactly the moment
    something may be impersonating their console.
    """
    from aiounas import SessionAuth, UnasAuthError, UnasClient

    async with aiohttp.ClientSession() as session:
        client = UnasClient(
            session,
            "127.0.0.1",
            SessionAuth("u", "p"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, _OTHER),
        )
        with pytest.raises(UnasCertificateMismatch) as caught:
            await client.async_prepare()
    assert not isinstance(caught.value, UnasAuthError)
    assert caught.value.got == tls_server.fingerprint


async def test_matching_pin_lets_the_client_through(tls_server: _Server) -> None:
    """Same path, right certificate: the pin must not break ordinary use."""
    from aiounas import ApiKeyAuth, SystemIdentity, UnasClient

    async with aiohttp.ClientSession() as session:
        client = UnasClient(
            session,
            "127.0.0.1",
            ApiKeyAuth("k"),
            port=tls_server.port,
            ssl=ssl_param(TlsMode.FINGERPRINT, tls_server.fingerprint),
        )
        # The stub answers `{}`, which SystemIdentity.from_api reads as a device
        # with empty fields. Getting a model back at all is the point: the
        # handshake was accepted and the request was served.
        assert isinstance(await client.get_identity(), SystemIdentity)


async def test_a_certificate_swapped_between_the_two_login_requests(
    tls_server: _Server,
) -> None:
    """The second guard in ``_login``, which a single server cannot reach.

    ``_login`` issues two requests: it primes CSRF from the console root, then
    posts the credentials. A mismatch normally stops the first one. This covers
    the case where the certificate changes in between — a reconnect landing on a
    different host behind the same address — because that is precisely the
    request that carries the password.
    """
    from aiounas.auth import SessionAuth

    expected, got = hashlib.sha256(b"pinned").digest(), hashlib.sha256(b"impostor").digest()

    class _Headers:
        """Just enough of aiohttp's multidict for ``SessionAuth._capture``."""

        @staticmethod
        def get(_name: str, default: object = None) -> object:
            return default

        @staticmethod
        def getall(_name: str, default: list[str] | None = None) -> list[str]:
            return default or []

    class _OkGet:
        headers = _Headers()

        async def __aenter__(self) -> _OkGet:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class _SwappingSession:
        def get(self, *_a: object, **_k: object) -> _OkGet:
            return _OkGet()

        def post(self, *_a: object, **_k: object) -> object:
            raise aiohttp.ServerFingerprintMismatch(expected, got, "127.0.0.1", 443)

    with pytest.raises(UnasCertificateMismatch) as caught:
        await SessionAuth("u", "p")._login(
            _SwappingSession(),  # type: ignore[arg-type]
            "https://127.0.0.1",
            ssl_param(TlsMode.FINGERPRINT, format_fingerprint(expected)),
        )
    assert caught.value.expected == format_fingerprint(expected)
    assert caught.value.got == format_fingerprint(got)


# --- the environment-driven trust used by the CLI and MCP server ---------------


def test_ssl_from_env_pins_when_a_fingerprint_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiounas.tls import ssl_from_env

    monkeypatch.setenv("UNAS_CERT_FINGERPRINT", _OTHER)
    monkeypatch.delenv("UNAS_VERIFY_SSL", raising=False)
    assert isinstance(ssl_from_env(), aiohttp.Fingerprint)


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_ssl_from_env_verifies_against_the_ca_store(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    from aiounas.tls import ssl_from_env

    monkeypatch.delenv("UNAS_CERT_FINGERPRINT", raising=False)
    monkeypatch.setenv("UNAS_VERIFY_SSL", value)
    assert ssl_from_env() is True


def test_ssl_from_env_defaults_to_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented rather than accidental: these are developer tools."""
    from aiounas.tls import ssl_from_env

    monkeypatch.delenv("UNAS_CERT_FINGERPRINT", raising=False)
    monkeypatch.delenv("UNAS_VERIFY_SSL", raising=False)
    assert ssl_from_env() is False


def test_a_pinned_fingerprint_wins_over_ca_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both set is not ambiguous: the specific certificate is the stronger claim."""
    from aiounas.tls import ssl_from_env

    monkeypatch.setenv("UNAS_CERT_FINGERPRINT", _OTHER)
    monkeypatch.setenv("UNAS_VERIFY_SSL", "1")
    assert isinstance(ssl_from_env(), aiohttp.Fingerprint)
