# OpenEVSE Control audit — 2026-09-10

## Compatibility target

- Home Assistant Core 2026.9.1
- Home Assistant OS 17.0
- HACS 2.0.5
- OpenEVSE ESP32 WiFi V4.0.0.BETA HTTP/RAPI API
- Continued support for modern override/claims firmware, with the modern fixture based on WiFi v5.1.5 / controller 8.2.2.EU

## Resolved issues

1. The uploaded integration assumed only `/override` and `/claims/*`, so it could not control V4 firmware. It now detects the API generation and uses V4's `/r?json=1&rapi=...` bridge when needed.
2. V4 mode control now matches the V4 web UI: `$FE` enables charging, Pause uses `$FS`, and `$FD` is used when the charger's `pause_uses_disabled` setting requests hard-disable behavior.
3. V4 current limits are read using `$GC`; current changes use `$SC` and are clamped to the reported range.
4. The invalid Auto option/button is not exposed on V4 because legacy RAPI has no modern claim-release semantic.
5. V4 capability and current-range discovery are cached; steady-state V4 polling is `/status` only.
6. Modern version counters continue to minimize `/config`, `/override`, and `/claims/target` reads.
7. Config entries use `runtime_data`; reconfigure, reauth, unload, translated errors, device info, and `DataUpdateCoordinator` patterns are retained for Home Assistant 2026.9.1.
8. Options use `OptionsFlowWithReload` without a competing config-entry update listener, avoiding the 2026.6+ double-reload deprecation.
9. Custom localization is shipped only in `translations/en.json`; `strings.json` is deliberately absent for the 2026 custom-integration translation rules.
10. Local brand assets are included inside the integration for Home Assistant 2026.3+ and at repository root for HACS validation.
11. HACS-required manifest metadata is present, including code owner, documentation, issue tracker, and version.
12. Diagnostics redact connection details, credentials, network identifiers, and charger secrets.
13. CI includes pytest/coverage, Ruff, Hassfest, and HACS validation on Python 3.14.2.
14. Release automation derives the GitHub release number from `manifest.json` and refuses to reuse an already-released version for a different commit.

## Repository-level HACS checks

HACS also checks GitHub repository metadata such as description and topics. Those are repository settings rather than files in the integration. The validation workflow intentionally does not ignore these checks.
