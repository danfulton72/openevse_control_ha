# OpenEVSE Control for Home Assistant

`openevse_control` is a local-polling Home Assistant custom integration for controlling OpenEVSE charging state and current without replacing Home Assistant's built-in `openevse` domain.

It supports both of the OpenEVSE WiFi API generations relevant to this project:

| OpenEVSE WiFi API | Detection / control | Supported controls |
| --- | --- | --- |
| V4-era HTTP/RAPI, including `V4.0.0.BETA` | `/status`, `/config`, `/r?json=1&rapi=...` | Enable, pause/disable, charge current |
| Modern override/claims API, validated against WiFi v5.1.5 | `/status`, `/config`, `/override`, `/claims`, `/claims/target` | Enable, Auto, Disable, charge current |

The V4 release recommends OpenEVSE controller firmware 7.1.2 or newer. The modern test fixture is based on WiFi v5.1.5 with controller firmware 8.2.2.EU.

## Entities

The integration creates a charge-mode select, a charge-rate number entity, and matching mode buttons. Modern firmware exposes **Enable / Auto / Disable**. V4 firmware exposes **Enable / Disable** only because the legacy RAPI interface has no equivalent of releasing a modern manual claim.

On V4, Disable follows the OpenEVSE web UI's Pause behavior: `$FS` (sleep) normally, or `$FD` (hard disable) when `pause_uses_disabled` is enabled in the charger configuration. Current limits are discovered with `$GC`, and current changes use `$SC`.

On modern firmware, mode and current controls preserve the override/claims behavior of the OpenEVSE UI. Higher-priority claims and Eco-divert current locks are surfaced as Home Assistant validation errors instead of reporting a manual change as successful when it cannot take effect.

## Efficient polling

The default poll interval is 10 seconds and can be changed from 5 to 300 seconds.

For modern firmware, `/status` version counters are used to fetch `/config`, `/override`, and `/claims/target` only when those resources have changed. For V4, capability detection, `/config`, and `$GC` current-range discovery are cached, so steady-state polling is a single `/status` request.

## Installation with HACS

This repository is laid out as a HACS integration repository. Add it as a **Custom repository** in HACS with category **Integration**, then install **OpenEVSE Control** and restart Home Assistant.

The repository targets Home Assistant **2026.9.1+** and HACS **2.0.5+**.

## Manual installation

Copy:

```text
custom_components/openevse_control
```

to:

```text
/config/custom_components/openevse_control
```

Restart Home Assistant, then go to **Settings → Devices & services → Add integration → OpenEVSE Control**.

## Configuration

Enter the OpenEVSE WiFi URL, for example `http://192.168.1.50` or `https://openevse.local`. If no scheme is supplied, HTTP is assumed. Optional HTTP Basic Authentication credentials are supported. For self-signed HTTPS certificates, disable certificate verification in the integration setup flow.

The config flow probes the charger with read-only requests and determines whether to use the modern override/claims API or the V4 HTTP/RAPI bridge. Reconfigure and reauthentication flows are included.

## Diagnostics and privacy

Home Assistant diagnostics are provided for the config entry. Connection details, credentials, hostnames, IP/MAC addresses, SSIDs, MQTT/Emoncms/Tesla secrets, and other charger identifiers are redacted.

## Development and validation

Pull requests and non-main pushes run:

```text
ruff
pytest + coverage
Hassfest
HACS validation
```

Tests use `pytest-homeassistant-custom-component==0.13.364` on Python 3.14.2, matching the Home Assistant 2026.9 generation. The suite includes fake modern and V4 chargers and verifies config flow, authentication, SSL handling, mode/current controls, claim locks, V4 RAPI commands, V4 current limits, and low-overhead polling.

A push/merge to `main` that changes the integration or `hacs.json` runs the same validation and then creates a GitHub Release whose tag is **exactly the `version` in `custom_components/openevse_control/manifest.json`**. If that version has already been released from another commit, the release workflow fails and requires the manifest version to be bumped. This prevents the manifest version and published release number from drifting apart.
