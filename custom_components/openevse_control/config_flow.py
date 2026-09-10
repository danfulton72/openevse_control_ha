"""Config flow for OpenEVSE Control."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import re
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    OpenEVSEAuthError,
    OpenEVSEClient,
    OpenEVSEConnectionError,
    OpenEVSERateLimitedError,
    OpenEVSEResponseError,
    OpenEVSESSLError,
    normalize_url,
)
from .const import (
    API_LEGACY,
    API_MODERN,
    CONF_AUTO_RELEASE,
    DEFAULT_AUTO_RELEASE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import is_legacy_api, is_modern_api

_LOGGER = logging.getLogger(__name__)

_USERNAME = TextSelector(TextSelectorConfig(autocomplete="username"))
_PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(),
        vol.Required(CONF_VERIFY_SSL, default=True): BooleanSelector(),
        vol.Optional(CONF_USERNAME): _USERNAME,
        vol.Optional(CONF_PASSWORD): _PASSWORD,
    }
)

AUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME): _USERNAME,
        vol.Optional(CONF_PASSWORD): _PASSWORD,
    }
)


class NotOpenEVSE(Exception):
    """Something answered, but it is not a compatible OpenEVSE WiFi module."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Validated setup information returned by a connection probe."""

    config: dict[str, Any]
    status: dict[str, Any]
    api_generation: str


async def _async_probe(hass: HomeAssistant, data: Mapping[str, Any]) -> ProbeResult:
    """Validate a supported OpenEVSE control API before creating an entry."""
    session = async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    client = OpenEVSEClient(
        session, data[CONF_URL], data.get(CONF_USERNAME), data.get(CONF_PASSWORD)
    )
    config = await client.get_config()
    status = await client.get_status()

    if is_modern_api(config, status):
        await client.get_override()
        await client.get_claims_target()
        await client.get_claims()
        return ProbeResult(config, status, API_MODERN)

    if is_legacy_api(config, status):
        # $GC is read-only and confirms that V4's HTTP/RAPI control bridge is usable.
        await client.legacy_get_current_range()
        return ProbeResult(config, status, API_LEGACY)

    raise NotOpenEVSE


def _normalize_mac(value: Any) -> str | None:
    """Return a canonical MAC-based unique ID when one is available."""
    if not isinstance(value, str):
        return None
    compact = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(compact) != 12:
        return None
    return "mac-" + compact.lower()


def _device_unique_id(probe: ProbeResult, url: str) -> str:
    """Return the best stable identifier exposed by OpenEVSE WiFi."""
    if mac := _normalize_mac(probe.status.get("macaddress")):
        return mac

    announce = probe.config.get("mqtt_announce_topic")
    if isinstance(announce, str) and announce.startswith("openevse/announce/"):
        suffix = announce.removeprefix("openevse/announce/").strip("/")
        if suffix:
            return f"openevse-{suffix}"
    if hostname := probe.config.get("hostname"):
        return str(hostname)
    return url


def _clean(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize form input into the values stored in the config entry."""
    data: dict[str, Any] = {
        CONF_URL: normalize_url(str(user_input[CONF_URL])),
        CONF_VERIFY_SSL: bool(user_input.get(CONF_VERIFY_SSL, True)),
    }
    if username := str(user_input.get(CONF_USERNAME) or "").strip():
        data[CONF_USERNAME] = username
    # Do not strip passwords; spaces may be intentional credentials.
    if password := user_input.get(CONF_PASSWORD):
        data[CONF_PASSWORD] = str(password)
    return data


async def _async_try(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[ProbeResult | None, dict[str, str]]:
    """Probe the charger and translate failures into form errors."""
    try:
        return await _async_probe(hass, data), {}
    except OpenEVSESSLError:
        return None, {"base": "ssl_error"}
    except OpenEVSEConnectionError:
        return None, {"base": "cannot_connect"}
    except OpenEVSEAuthError:
        return None, {"base": "invalid_auth"}
    except OpenEVSERateLimitedError:
        return None, {"base": "rate_limited"}
    except (OpenEVSEResponseError, NotOpenEVSE):
        return None, {"base": "not_openevse"}
    except Exception:
        _LOGGER.exception("Unexpected error probing charger")
        return None, {"base": "unknown"}


class OpenEVSEControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OpenEVSEControlOptionsFlow:
        """Return the options flow."""
        return OpenEVSEControlOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for URL, SSL verification, and optional web credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _clean(user_input)
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                probe, errors = await _async_try(self.hass, data)
                if probe is not None:
                    await self.async_set_unique_id(
                        _device_unique_id(probe, data[CONF_URL])
                    )
                    self._abort_if_unique_id_configured(updates=data)
                    return self.async_create_entry(
                        title=str(probe.config.get("hostname") or "OpenEVSE"),
                        data=data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    @override
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change URL, SSL settings, or credentials after setup."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _clean(user_input)
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                probe, errors = await _async_try(self.hass, data)
                if probe is not None:
                    await self.async_set_unique_id(
                        _device_unique_id(probe, data[CONF_URL])
                    )
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )

    @override
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after a 401."""
        return await self.async_step_reauth_confirm()

    @override
    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new web credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            base = {
                key: value
                for key, value in entry.data.items()
                if key not in (CONF_USERNAME, CONF_PASSWORD)
            }
            data = _clean({**base, **user_input})
            probe, errors = await _async_try(self.hass, data)
            if probe is not None:
                await self.async_set_unique_id(
                    _device_unique_id(probe, data[CONF_URL])
                )
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                AUTH_SCHEMA, {CONF_USERNAME: entry.data.get(CONF_USERNAME)}
            ),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )


class OpenEVSEControlOptionsFlow(OptionsFlowWithReload):
    """Manage polling interval and modern manual-current behavior."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(title="", data=user_input)

        schema_fields: dict[Any, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            )
        }

        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or not coordinator.data.legacy:
            schema_fields[
                vol.Required(
                    CONF_AUTO_RELEASE,
                    default=self.config_entry.options.get(
                        CONF_AUTO_RELEASE, DEFAULT_AUTO_RELEASE
                    ),
                )
            ] = BooleanSelector()

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_fields)
        )
