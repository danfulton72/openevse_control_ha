"""Constants for the OpenEVSE Control integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "openevse_control"

CONF_AUTO_RELEASE: Final = "auto_release"

DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300
DEFAULT_AUTO_RELEASE: Final = True

API_MODERN: Final = "modern"
API_LEGACY: Final = "v4_rapi"

MODE_ENABLE: Final = "enable"
MODE_AUTO: Final = "auto"
MODE_DISABLE: Final = "disable"
MODES: Final = [MODE_ENABLE, MODE_AUTO, MODE_DISABLE]
LEGACY_MODES: Final = [MODE_ENABLE, MODE_DISABLE]

MIN_CHARGE_RATE: Final = 6
DIVERT_MODE_ECO: Final = 2

# OpenEVSE WiFi v5 claim clients.
CLIENT_MANUAL: Final = 65537
CLIENT_LIMIT: Final = 65542
CLIENT_OCPP: Final = 65545
CLIENT_RFID: Final = 65546
CLIENT_NAMES: Final[dict[int, str]] = {
    65537: "manual",
    65538: "divert",
    65539: "boost",
    65540: "timer",
    65542: "limit",
    65543: "error",
    65544: "ohm",
    65545: "ocpp",
    65546: "rfid",
    65547: "mqtt",
    65548: "shaper",
}
PRIORITY_MANUAL: Final = 1000

# Claims/status updates are asynchronous after control writes.
COMMAND_SETTLE_DELAY: Final = 0.75


def client_name(client_id: int | None) -> str | None:
    """Return a readable name for a claim client ID."""
    if client_id is None:
        return None
    return CLIENT_NAMES.get(client_id, f"client_{client_id}")
