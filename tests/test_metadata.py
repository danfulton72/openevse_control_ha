"""Repository metadata tests that do not require a live charger."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "openevse_control" / "manifest.json"


def test_manifest_has_hacs_required_fields() -> None:
    """Keep the integration manifest complete for HACS."""
    manifest = json.loads(MANIFEST.read_text())
    assert {
        "codeowners",
        "documentation",
        "domain",
        "issue_tracker",
        "name",
        "version",
    }.issubset(manifest)
    assert manifest["domain"] == "openevse_control"
    assert manifest["version"]


def test_custom_component_uses_runtime_translations_only() -> None:
    """Custom integrations use translations/en.json, not Core's strings.json."""
    integration = MANIFEST.parent
    assert (integration / "translations" / "en.json").is_file()
    assert not (integration / "strings.json").exists()


def test_brand_assets_exist_for_hacs_and_home_assistant() -> None:
    """Provide both HACS root branding and HA 2026.3+ local branding."""
    assert (ROOT / "brand" / "icon.png").is_file()
    assert (MANIFEST.parent / "brand" / "icon.png").is_file()
