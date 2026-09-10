"""Diagnostics support for OpenEVSE Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import OpenEVSEConfigEntry

_REDACT_ENTRY = {CONF_PASSWORD, CONF_URL, CONF_USERNAME, "unique_id"}
_REDACT_CHARGER = {
    "apikey",
    "emoncms_apikey",
    "emoncms_server",
    "hostname",
    "ipaddress",
    "macaddress",
    "mqtt_announce_topic",
    "mqtt_pass",
    "mqtt_server",
    "mqtt_topic",
    "pass",
    "password",
    "ssid",
    "tesla_password",
    "tesla_username",
    "tesla_vehicle_id",
    "www_password",
    "www_username",
}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: OpenEVSEConfigEntry
) -> dict[str, Any]:
    """Return a privacy-conscious diagnostic snapshot."""
    data = entry.runtime_data.data
    return {
        "config_entry": async_redact_data(entry.as_dict(), _REDACT_ENTRY),
        "api_generation": data.api_generation,
        "status": async_redact_data(data.status, _REDACT_CHARGER),
        "config": async_redact_data(data.config, _REDACT_CHARGER),
        "override": data.override,
        "target": data.target,
        "current_range": {
            "min": data.min_charge_rate,
            "max": data.max_charge_rate,
        },
    }
