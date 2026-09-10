"""Async HTTP client for OpenEVSE WiFi control APIs."""

from __future__ import annotations

import json
import logging
from typing import Any, Final

import aiohttp
from yarl import URL

from .const import DEFAULT_USERNAME

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=15)
_NO_OVERRIDE_MESSAGE: Final = "Failed to release manual override"


class OpenEVSEError(Exception):
    """Base class for OpenEVSE errors."""


class OpenEVSEConnectionError(OpenEVSEError):
    """The charger could not be reached."""


class OpenEVSESSLError(OpenEVSEConnectionError):
    """TLS handshake or certificate verification failed."""


class OpenEVSEAuthError(OpenEVSEError):
    """The charger rejected the credentials (HTTP 401)."""


class OpenEVSERateLimitedError(OpenEVSEError):
    """The charger is throttling after repeated bad credentials (HTTP 429)."""


class OpenEVSEResponseError(OpenEVSEError):
    """The charger returned something unexpected or rejected a command."""


def normalize_url(raw: str) -> str:
    """Normalize user input, defaulting to HTTP and rejecting unusable URLs."""
    raw = raw.strip()
    if not raw:
        raise ValueError("empty URL")
    if "://" not in raw:
        raw = f"http://{raw}"
    url = URL(raw)
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError(f"not an http(s) URL: {raw}")
    return str(url.with_query(None).with_fragment(None)).rstrip("/")


class OpenEVSEClient:
    """Talk to an OpenEVSE WiFi module."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base = normalize_url(url)
        self._auth: aiohttp.BasicAuth | None = None
        if username is not None or password is not None:
            effective_username = username or (DEFAULT_USERNAME if password else "")
            self._auth = aiohttp.BasicAuth(effective_username, password or "")

    @property
    def url(self) -> str:
        """Return the charger base URL."""
        return self._base

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        params: dict[str, str] | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> tuple[int, Any]:
        """Perform a request and return status plus decoded JSON or text."""
        url = f"{self._base}{path}"
        _LOGGER.debug("%s %s", method, url)
        try:
            async with self._session.request(
                method,
                url,
                json=body,
                params=params,
                auth=self._auth,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                text = await resp.text()
                status = resp.status
        except aiohttp.ClientSSLError as err:
            raise OpenEVSESSLError(str(err)) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise OpenEVSEConnectionError(
                f"{method} {url} failed: {err or type(err).__name__}"
            ) from err

        _LOGGER.debug("%s %s -> %s %s", method, path, status, text[:500])

        if status == 401:
            raise OpenEVSEAuthError("Credentials rejected")
        if status == 429:
            raise OpenEVSERateLimitedError(
                "Charger is locked out after too many failed logins"
            )
        if status >= 400 and status not in allow_status:
            raise OpenEVSEResponseError(
                f"{method} {path} returned HTTP {status}: {text[:200]}"
            )

        try:
            return status, json.loads(text) if text else None
        except ValueError:
            return status, text

    async def _get_dict(self, path: str) -> dict[str, Any]:
        """GET a JSON object."""
        _, data = await self._request("GET", path)
        if not isinstance(data, dict):
            raise OpenEVSEResponseError(f"GET {path} did not return a JSON object")
        return data

    async def get_status(self) -> dict[str, Any]:
        """Return /status."""
        return await self._get_dict("/status")

    async def get_config(self) -> dict[str, Any]:
        """Return /config."""
        return await self._get_dict("/config")

    # Modern override/claims API -------------------------------------------------

    async def get_override(self) -> dict[str, Any]:
        """Return the manual override, or an empty mapping when inactive."""
        data = await self._get_dict("/override")
        if set(data) == {"msg"}:
            return {}
        return data

    async def get_claims_target(self) -> dict[str, Any]:
        """Return resolved claim properties and ownership."""
        data = await self._get_dict("/claims/target")
        if not isinstance(data.get("properties"), dict) or not isinstance(
            data.get("claims"), dict
        ):
            raise OpenEVSEResponseError(
                "GET /claims/target did not return properties/claims objects"
            )
        return data

    async def get_claims(self) -> list[dict[str, Any]]:
        """Return all EVSE claims."""
        _, data = await self._request("GET", "/claims")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise OpenEVSEResponseError("GET /claims did not return a JSON array")
        return data

    async def set_override(self, props: dict[str, Any]) -> None:
        """Create or replace the manual override."""
        await self._request("POST", "/override", props)

    async def clear_override(self) -> None:
        """Release the manual override; tolerate the known idempotent failure."""
        status, data = await self._request("DELETE", "/override", allow_status=(500,))
        if status != 500:
            return
        message = data.get("msg") if isinstance(data, dict) else None
        if message == _NO_OVERRIDE_MESSAGE:
            _LOGGER.debug("Manual override was already released")
            return
        raise OpenEVSEResponseError(
            f"DELETE /override returned HTTP 500: {str(data)[:200]}"
        )

    # V4-era HTTP/RAPI bridge ----------------------------------------------------

    async def rapi(self, command: str) -> list[str]:
        """Run one RAPI command via V4's JSON HTTP bridge and return response tokens."""
        _, data = await self._request(
            "GET", "/r", params={"json": "1", "rapi": command}
        )
        if not isinstance(data, dict):
            raise OpenEVSEResponseError("RAPI endpoint did not return a JSON object")
        response = data.get("ret")
        if not isinstance(response, str):
            error = data.get("error")
            raise OpenEVSEResponseError(
                f"RAPI command {command!r} returned no response: {error or data}"
            )
        response = response.strip()
        if response.startswith("$NK"):
            raise OpenEVSEResponseError(f"RAPI command {command!r} was rejected")
        if not response.startswith("$OK"):
            raise OpenEVSEResponseError(
                f"RAPI command {command!r} returned unexpected response {response!r}"
            )
        payload = response[3:].strip()
        return payload.split() if payload else []

    async def legacy_get_current_range(self) -> tuple[int, int]:
        """Return the V4 controller's allowed current range using $GC."""
        tokens = await self.rapi("$GC")
        if len(tokens) < 2:
            raise OpenEVSEResponseError("$GC did not return minimum and maximum current")
        try:
            minimum, maximum = int(tokens[0]), int(tokens[1])
        except ValueError as err:
            raise OpenEVSEResponseError("$GC returned invalid current limits") from err
        if minimum <= 0 or maximum < minimum:
            raise OpenEVSEResponseError("$GC returned an invalid current range")
        return minimum, maximum

    async def legacy_enable(self) -> None:
        """Enable charging on V4 firmware using $FE."""
        await self.rapi("$FE")

    async def legacy_sleep(self) -> None:
        """Pause charging on V4 firmware using $FS."""
        await self.rapi("$FS")

    async def legacy_disable(self) -> None:
        """Hard-disable charging on V4 firmware using $FD."""
        await self.rapi("$FD")

    async def legacy_set_current(self, amps: int) -> None:
        """Set current capacity on V4 firmware using $SC."""
        await self.rapi(f"$SC {int(amps)}")
