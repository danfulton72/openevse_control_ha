"""Data coordinator for OpenEVSE Control."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    OpenEVSEAuthError,
    OpenEVSEClient,
    OpenEVSEError,
    OpenEVSERateLimitedError,
)
from .const import (
    API_LEGACY,
    API_MODERN,
    CLIENT_LIMIT,
    CLIENT_MANUAL,
    CLIENT_OCPP,
    CLIENT_RFID,
    COMMAND_SETTLE_DELAY,
    CONF_AUTO_RELEASE,
    DEFAULT_AUTO_RELEASE,
    DEFAULT_SCAN_INTERVAL,
    DIVERT_MODE_ECO,
    DOMAIN,
    LEGACY_MODES,
    MIN_CHARGE_RATE,
    MODE_AUTO,
    MODE_DISABLE,
    MODE_ENABLE,
    MODES,
    PRIORITY_MANUAL,
    client_name,
)

_LOGGER = logging.getLogger(__name__)

type OpenEVSEConfigEntry = ConfigEntry["OpenEVSECoordinator"]


def is_modern_api(config: dict[str, Any], status: dict[str, Any]) -> bool:
    """Return whether status/config describe the modern override/claims API."""
    return "max_current_soft" in config and {
        "max_current",
        "config_version",
        "claims_version",
        "override_version",
    }.issubset(status)


def is_legacy_api(config: dict[str, Any], status: dict[str, Any]) -> bool:
    """Return whether status/config look like the V4 HTTP/RAPI API."""
    return {"version", "firmware"}.issubset(config) and {"state", "pilot"}.issubset(
        status
    )


def _as_bool(value: Any) -> bool:
    """Coerce common OpenEVSE config representations to bool."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(slots=True)
class OpenEVSEData:
    """Snapshot used by OpenEVSE entities."""

    status: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    override: dict[str, Any] = field(default_factory=dict)
    target: dict[str, Any] = field(default_factory=dict)
    api_generation: str = API_MODERN
    legacy_min_current: int | None = None
    legacy_max_current: int | None = None

    @property
    def legacy(self) -> bool:
        """Return whether this charger uses the V4 HTTP/RAPI bridge."""
        return self.api_generation == API_LEGACY

    @property
    def target_properties(self) -> dict[str, Any]:
        """Return effective claim properties."""
        properties = self.target.get("properties")
        return properties if isinstance(properties, dict) else {}

    @property
    def target_claims(self) -> dict[str, Any]:
        """Return claim ownership."""
        claims = self.target.get("claims")
        return claims if isinstance(claims, dict) else {}

    @property
    def available_modes(self) -> list[str]:
        """Return charge modes implemented by the connected firmware."""
        return list(LEGACY_MODES if self.legacy else MODES)

    @property
    def mode(self) -> str:
        """Return the current charge-control mode."""
        if self.legacy:
            try:
                state = int(self.status.get("state"))
            except (TypeError, ValueError):
                return MODE_ENABLE
            return MODE_DISABLE if state in (254, 255) else MODE_ENABLE

        if self.target_claims.get("state") == CLIENT_MANUAL:
            state = self.target_properties.get("state")
            if state == "active":
                return MODE_ENABLE
            if state == "disabled":
                return MODE_DISABLE
        return MODE_AUTO

    @property
    def state_controlled_by(self) -> str | None:
        """Return the client controlling charger state."""
        if self.legacy:
            return None
        return client_name(self.target_claims.get("state"))

    @property
    def charge_rate_controlled_by(self) -> str | None:
        """Return the client controlling charge current."""
        if self.legacy:
            return None
        return client_name(self.target_claims.get("charge_current"))

    @property
    def min_charge_rate(self) -> int:
        """Return the minimum current supported by the charger."""
        if self.legacy and self.legacy_min_current is not None:
            return self.legacy_min_current
        return MIN_CHARGE_RATE

    @property
    def max_charge_rate(self) -> int:
        """Return the maximum configured/supported current."""
        if self.legacy and self.legacy_max_current is not None:
            return self.legacy_max_current

        value = self.config.get("max_current_soft")
        if value is None:
            value = self.status.get("max_current")
        try:
            return max(self.min_charge_rate, int(value))
        except (TypeError, ValueError):
            return self.min_charge_rate

    @property
    def status_max_current(self) -> int | None:
        """Return the effective max_current reported by modern /status."""
        if self.legacy:
            return None
        try:
            return int(self.status["max_current"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def charge_rate(self) -> int | None:
        """Return the effective charge-current set point."""
        if self.legacy:
            try:
                return int(self.status["pilot"])
            except (KeyError, TypeError, ValueError):
                return None

        current = self.target_properties.get("charge_current")
        if current is not None:
            try:
                return min(int(current), self.max_charge_rate)
            except (TypeError, ValueError):
                return None
        if self.config.get("max_current_soft") is not None:
            return self.max_charge_rate
        return None

    @property
    def mode_locked_by(self) -> str | None:
        """Return why the modern web UI would lock mode controls."""
        if self.legacy:
            return None
        claim = self.target_claims.get("state")
        if claim in (CLIENT_OCPP, CLIENT_LIMIT):
            return client_name(claim)
        if claim == CLIENT_RFID and not self.status.get("rfid_auth"):
            return client_name(claim)
        return None

    @property
    def eco_mode(self) -> bool:
        """Return whether solar-divert Eco mode is active."""
        try:
            return int(self.status.get("divertmode")) == DIVERT_MODE_ECO
        except (TypeError, ValueError):
            return False


class OpenEVSECoordinator(DataUpdateCoordinator[OpenEVSEData]):
    """Poll the charger and serialize control commands."""

    config_entry: OpenEVSEConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OpenEVSEConfigEntry,
        client: OpenEVSEClient,
    ) -> None:
        """Initialize the coordinator."""
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self._versions: dict[str, Any] = {}
        self._cache = OpenEVSEData()
        self._api_generation: str | None = None
        self._legacy_current_range: tuple[int, int] | None = None
        self._command_lock = asyncio.Lock()

    async def _async_update_data(self) -> OpenEVSEData:
        """Fetch current state, minimizing steady-state HTTP traffic."""
        try:
            status = await self.client.get_status()

            if self._api_generation is None:
                self._cache.config = await self.client.get_config()
                if is_modern_api(self._cache.config, status):
                    self._api_generation = API_MODERN
                    # Validate the control surface before exposing entities.
                    self._cache.override = await self.client.get_override()
                    self._cache.target = await self.client.get_claims_target()
                    await self.client.get_claims()
                    for key in (
                        "config_version",
                        "override_version",
                        "claims_version",
                    ):
                        self._versions[key] = status.get(key)
                elif is_legacy_api(self._cache.config, status):
                    self._api_generation = API_LEGACY
                    self._legacy_current_range = (
                        await self.client.legacy_get_current_range()
                    )
                else:
                    raise UpdateFailed("The device does not expose a supported OpenEVSE API")

            elif self._api_generation == API_MODERN:
                if self._stale(status, "config_version"):
                    self._cache.config = await self.client.get_config()
                    self._versions["config_version"] = status.get("config_version")
                if self._stale(status, "override_version"):
                    self._cache.override = await self.client.get_override()
                    self._versions["override_version"] = status.get("override_version")
                if self._stale(status, "claims_version"):
                    self._cache.target = await self.client.get_claims_target()
                    self._versions["claims_version"] = status.get("claims_version")

            elif self._legacy_current_range is None:
                self._legacy_current_range = await self.client.legacy_get_current_range()

        except OpenEVSEAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except OpenEVSERateLimitedError as err:
            raise UpdateFailed(str(err)) from err
        except OpenEVSEError as err:
            raise UpdateFailed(f"Error talking to charger: {err}") from err

        legacy_min = legacy_max = None
        if self._legacy_current_range is not None:
            legacy_min, legacy_max = self._legacy_current_range

        return OpenEVSEData(
            status=status,
            config=self._cache.config,
            override=self._cache.override,
            target=self._cache.target,
            api_generation=self._api_generation or API_MODERN,
            legacy_min_current=legacy_min,
            legacy_max_current=legacy_max,
        )

    def _stale(self, status: dict[str, Any], key: str) -> bool:
        """Return whether a modern versioned resource needs refetching."""
        return key not in self._versions or self._versions.get(key) != status.get(key)

    async def async_set_mode(self, mode: str) -> None:
        """Set the charge-control mode using the connected firmware's API."""
        available_modes = self.data.available_modes
        if mode not in available_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_mode",
                translation_placeholders={
                    "mode": mode,
                    "modes": ", ".join(available_modes),
                },
            )

        if self.data.legacy:

            async def _legacy_send() -> None:
                if mode == MODE_ENABLE:
                    await self.client.legacy_enable()
                    return
                if _as_bool(self.data.config.get("pause_uses_disabled")):
                    await self.client.legacy_disable()
                else:
                    await self.client.legacy_sleep()

            await self._async_command(_legacy_send)
            return

        if (locked_by := self.data.mode_locked_by) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_locked",
                translation_placeholders={"client": locked_by},
            )

        async def _send() -> None:
            override = await self.client.get_override()
            if mode == MODE_AUTO:
                if override:
                    await self.client.clear_override()
                return

            body: dict[str, Any] = {
                "state": "active" if mode == MODE_ENABLE else "disabled"
            }
            charge_current = override.get("charge_current")
            if charge_current is None:
                charge_current = self.data.config.get("max_current_soft")
            if charge_current is not None:
                body["charge_current"] = charge_current
            await self.client.set_override(body)

        await self._async_command(_send)

    async def async_set_charge_rate(self, amps: int) -> None:
        """Set the charge-current limit."""
        if self.data.eco_mode:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="rate_locked_eco"
            )
        amps = max(
            self.data.min_charge_rate,
            min(int(amps), self.data.max_charge_rate),
        )

        if self.data.legacy:
            await self._async_command(lambda: self.client.legacy_set_current(amps))
            return

        async def _send() -> None:
            await self._raise_if_rate_claimed()
            override = await self.client.get_override()
            auto_release = bool(
                self.config_entry.options.get(CONF_AUTO_RELEASE, DEFAULT_AUTO_RELEASE)
            )

            if (
                self.data.mode == MODE_AUTO
                and self.data.status_max_current is not None
                and amps == self.data.status_max_current
            ):
                if (
                    override.get("state") is None
                    and override.get("max_current") is None
                    and override.get("auto_release") is False
                ):
                    if "charge_current" in override:
                        await self.client.clear_override()
                else:
                    override.pop("charge_current", None)
                    await self.client.set_override(override)
                return

            override["charge_current"] = amps
            override["auto_release"] = auto_release
            await self.client.set_override(override)

        await self._async_command(_send)

    async def _raise_if_rate_claimed(self) -> None:
        """Reject a current change behind a higher-priority modern claim."""
        owner = self.data.target_claims.get("charge_current")
        if owner is None or owner == CLIENT_MANUAL:
            return
        claims = await self.client.get_claims()
        priority = next(
            (claim.get("priority") for claim in claims if claim.get("client") == owner),
            None,
        )
        if priority is not None and priority > PRIORITY_MANUAL:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="rate_locked",
                translation_placeholders={"client": client_name(owner) or "?"},
            )

    async def _async_command(self, send: Callable[[], Awaitable[None]]) -> None:
        """Run one command, map API errors, then refresh state."""
        async with self._command_lock:
            try:
                await send()
            except OpenEVSEAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="invalid_auth"
                ) from err
            except OpenEVSEError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

            if self._api_generation == API_MODERN:
                self._versions.pop("override_version", None)
                self._versions.pop("claims_version", None)
            await asyncio.sleep(COMMAND_SETTLE_DELAY)
            await self.async_refresh()
