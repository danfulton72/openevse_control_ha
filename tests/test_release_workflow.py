"""Release workflow invariants."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "openevse_control" / "manifest.json"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_derives_tag_from_manifest() -> None:
    """Keep GitHub release/tag version tied to manifest.json."""
    manifest = json.loads(MANIFEST.read_text())
    workflow_text = RELEASE.read_text()

    assert manifest["version"]
    assert 'manifest="custom_components/openevse_control/manifest.json"' in workflow_text
    assert "jq -er '.version'" in workflow_text
    assert 'gh release create "$VERSION"' in workflow_text
    assert '--target "$GITHUB_SHA"' in workflow_text


def test_release_workflow_runs_only_after_validation_on_main() -> None:
    """A merged integration change must validate before release publication."""
    workflow = yaml.load(RELEASE.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert triggers["push"]["branches"] == ["main"]
    assert "custom_components/openevse_control/**" in triggers["push"]["paths"]
    assert workflow["jobs"]["release"]["needs"] == "validate"
