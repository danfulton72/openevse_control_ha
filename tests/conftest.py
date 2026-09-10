"""Fixtures."""

from __future__ import annotations

import asyncio
import ssl
import subprocess

import pytest
from aiohttp import web
from aiohttp.test_utils import unused_port

from .fake_openevse import FakeOpenEVSE


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/openevse_control."""
    return


@pytest.fixture(autouse=True)
def allow_localhost_sockets(socket_enabled):
    """The fake charger is a real local HTTP(S) server."""
    return


@pytest.fixture(autouse=True)
def no_settle_delay(monkeypatch):
    """Skip the post-command wait in tests."""
    monkeypatch.setattr(
        "custom_components.openevse_control.coordinator.COMMAND_SETTLE_DELAY", 0
    )


async def _serve(fake: FakeOpenEVSE, ssl_ctx: ssl.SSLContext | None = None):
    runner = web.AppRunner(fake.app)
    await runner.setup()
    port = unused_port()
    site = web.TCPSite(runner, "127.0.0.1", port, ssl_context=ssl_ctx)
    await site.start()
    fake.url = f"{'https' if ssl_ctx else 'http'}://127.0.0.1:{port}"
    return runner


@pytest.fixture
async def evse(hass):
    """Plain-HTTP fake charger, no password."""
    fake = FakeOpenEVSE()
    runner = await _serve(fake)
    yield fake
    await runner.cleanup()


@pytest.fixture
async def evse_v4(hass):
    """Plain-HTTP fake charger exposing the V4-era HTTP/RAPI API."""
    fake = FakeOpenEVSE(legacy=True)
    runner = await _serve(fake)
    yield fake
    await runner.cleanup()


@pytest.fixture
async def evse_auth(hass):
    """Fake charger with a password set."""
    fake = FakeOpenEVSE(password="s3cret", username="admin")
    runner = await _serve(fake)
    yield fake
    await runner.cleanup()


@pytest.fixture
async def evse_https(hass, tmp_path):
    """HTTPS fake charger with a self-signed certificate."""
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    await asyncio.to_thread(
        subprocess.run,
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=openevse.local",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)
    fake = FakeOpenEVSE()
    runner = await _serve(fake, ctx)
    yield fake
    await runner.cleanup()
