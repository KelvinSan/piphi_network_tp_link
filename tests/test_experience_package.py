from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "experiences" / "kasa-smart-home" / "package.source.json"
ENTRY = SOURCE.parent / "assets" / "kasa-widget.mjs"
CAPABILITY_MATRIX = ROOT / "capabilities" / "device_matrix.json"
_builder_spec = importlib.util.spec_from_file_location(
    "kasa_experience_builder", ROOT / "scripts" / "build_experience.py"
)
assert _builder_spec is not None and _builder_spec.loader is not None
_builder = importlib.util.module_from_spec(_builder_spec)
sys.modules[_builder_spec.name] = _builder
_builder_spec.loader.exec_module(_builder)
build = _builder.build

ALLOWED_THEME_TOKENS = {
    "--piphi-experience-accent",
    "--piphi-experience-surface",
    "--piphi-experience-tile-surface",
    "--piphi-experience-tile-border",
    "--piphi-experience-shadow",
    "--piphi-experience-tile-shadow",
    "--piphi-experience-radius",
    "--piphi-experience-gap",
    "--piphi-experience-energy-accent",
}


def _source() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def test_capability_matrix_accounts_for_manifest_and_simulator_surface() -> None:
    matrix = json.loads(CAPABILITY_MATRIX.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "src" / "manifest.json").read_text(encoding="utf-8"))
    implemented_capabilities = {
        item["id"] for item in matrix["capabilities"] if item["status"] == "implemented"
    }
    implemented_commands = {
        item["id"] for item in matrix["commands"] if item["status"] == "implemented"
    }
    assert implemented_capabilities == set(manifest["capabilities"])
    assert implemented_commands == set(manifest["commands"])
    assert {profile["id"] for profile in matrix["device_profiles"]} == {
        "mini-plug",
        "energy-plug",
        "wall-switch",
        "dimmer-switch",
        "white-bulb",
        "color-bulb",
        "light-strip",
        "power-strip",
        "sensor-hub",
    }
    assert all(profile["simulated"] is True for profile in matrix["device_profiles"])
    assert all(
        set(profile["capabilities"]) <= implemented_capabilities
        for profile in matrix["device_profiles"]
    )
    assert matrix["completion"] == {
        "status": "implementation_complete",
        "scope": "Negotiated local Kasa plugs, switches, lights, strips, energy monitors, and supported sensor hubs",
        "automated_validation": "passed",
        "simulator_validation": "passed",
        "physical_device_validation": "pending",
    }


def test_package_contains_control_energy_stacked_and_environment_widgets() -> None:
    source = _source()
    assert source["origin"] == "integration"
    assert source["owning_integration_id"] == "tp-link-kasa-local-api"
    assert [widget["id"] for widget in source["widgets"]] == [
        "device-control",
        "energy-monitor",
        "smart-plug",
        "environment-monitor",
    ]
    assert [widget["runtime"] for widget in source["widgets"]] == [
        "sandboxed_bundle",
        "declarative",
        "sandboxed_bundle",
        "declarative",
    ]


def test_bindings_match_runtime_capabilities_and_are_device_scoped() -> None:
    source = _source()
    capabilities = set(json.loads((ROOT / "src" / "manifest.json").read_text())["capabilities"])
    for widget in source["widgets"]:
        slots = {slot["id"]: slot for slot in widget["binding_slots"]}
        assert slots
        for slot in slots.values():
            assert slot["compatible_integration_ids"] == ["tp-link-kasa-local-api"]
            assert set(slot["capability_requirements"]) <= capabilities
            assert 5 <= slot["data_delivery"]["stale_after_seconds"] <= 604_800
        binding_targets = {
            target["binding_slot_id"]
            for target in widget["interaction_targets"]
            if target["kind"] == "binding"
        }
        assert binding_targets <= slots.keys()


def test_command_widgets_are_explicitly_permissioned_and_allow_listed() -> None:
    widgets = {widget["id"]: widget for widget in _source()["widgets"]}
    assert widgets["energy-monitor"].get("permissions", []) == []
    for widget_id in ("device-control", "smart-plug"):
        widget = widgets[widget_id]
        assert widget["permissions"] == ["host.executeCommand"]
        assert widget["allowed_commands"]
        assert all(
            "command" in target["allowed_actions"]
            for target in widget["interaction_targets"]
            if target["kind"] == "binding" and target["default_action"] == "command"
        )


def test_themes_are_bounded_and_core_typography_remains_authoritative() -> None:
    stylesheets = {
        theme["stylesheet"]
        for widget in _source()["widgets"]
        for theme in widget["themes"]
    }
    assert stylesheets == {"themes/kasa.css", "themes/quiet.css"}
    for stylesheet in stylesheets:
        css = (SOURCE.parent / stylesheet).read_text(encoding="utf-8")
        assert css.strip().startswith(":root {")
        assert "@import" not in css and "url(" not in css and "!important" not in css
        tokens = {
            line.split(":", 1)[0].strip()
            for line in css.splitlines()
            if line.strip().startswith("--")
        }
        assert tokens and tokens <= ALLOWED_THEME_TOKENS
        assert "--piphi-experience-shadow: none;" in css
        assert "--piphi-experience-tile-shadow: none;" in css
    assert all(widget["presentation"]["typography"] == "core" for widget in _source()["widgets"])


def test_sandbox_widget_has_accessible_responsive_loading_and_error_paths() -> None:
    source = ENTRY.read_text(encoding="utf-8")
    assert 'aria-label="Turn ${isOn ? "off" : "on"}"' in source
    assert 'aria-pressed="${isOn}"' in source
    assert 'role="alert"' in source
    assert "@container (max-width: 360px)" in source
    assert "prefers-reduced-motion" in source
    assert "host.subscribeState" in source
    assert "event?.kind === \"error\"" in source
    assert "Unable to load device state" in source
    assert "—" in source


def test_device_control_is_compact_theme_safe_and_opens_core_details() -> None:
    source = ENTRY.read_text(encoding="utf-8")
    assert "min-height: 0" in source
    assert "min-height: 82px" in source
    assert "width: 46px; height: 46px" in source
    assert 'data-active="${isOn}"' in source
    assert 'class="kasa__state-dot"' in source
    assert 'class="kasa__level-fill"' in source
    assert 'data-target="${cardTarget}"' in source
    assert 'aria-label="View Kasa device details"' in source
    assert 'aria-label="View brightness details"' in source
    assert "activateTarget(element.dataset.target)" in source
    assert "Unable to open device details." in source
    assert "background: #" not in source
    assert "--piphi-widget-muted-text" not in source
    assert "--piphi-widget-text-muted" in source
    assert 'class="kasa__level"' in source
    assert 'density === "expanded"' in source


def test_device_control_defaults_to_compact_density_with_an_expanded_option() -> None:
    widget = next(
        item for item in _source()["widgets"] if item["id"] == "device-control"
    )
    assert widget["default_column_span"] == 4
    assert widget["default_row_span"] == 3
    assert widget["settings_schema_version"] == "2"
    assert widget["settings"] == [
        {
            "id": "dashboard_density",
            "type": "select",
            "label": "Dashboard density",
            "description": "Compact is recommended. Expanded controls use the extra space to keep brightness visible.",
            "default": "compact",
            "options": [
                {
                    "label": "Compact (recommended)",
                    "value": "compact",
                    "recommended_column_span": 4,
                    "recommended_row_span": 3,
                },
                {
                    "label": "Expanded controls",
                    "value": "expanded",
                    "recommended_column_span": 4,
                    "recommended_row_span": 5,
                },
            ],
        }
    ]
    assert widget["settings_migrations"] == [
        {
            "from": "1",
            "to": "2",
            "defaults": {"dashboard_density": "compact"},
            "remove": ["show_brightness"],
        }
    ]


def test_energy_monitor_uses_a_compact_dashboard_footprint() -> None:
    widget = next(
        item for item in _source()["widgets"] if item["id"] == "energy-monitor"
    )
    assert widget["default_column_span"] == 4
    assert widget["default_row_span"] == 2
    assert all(
        item.get("emphasis") == "compact"
        for item in widget["recipe"]["items"]
    )


def test_sandbox_widget_announces_visual_readiness_before_live_subscription() -> None:
    source = ENTRY.read_text(encoding="utf-8")
    ready_call = source.index("await host.ready")
    subscription_call = source.index("await host.subscribeState")

    assert ready_call < subscription_call


def test_browser_helpers_cover_empty_snapshot_points_and_power_commands() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    script = f"""
      import {{ activateTarget, cardTargetForMode, commandForPower, dashboardDensity, formatReading, statesFromEvent }} from {json.dumps(ENTRY.as_uri())};
      const interactions = [];
      await activateTarget(cardTargetForMode('device-control'), {{activateInteraction: async (targetId) => interactions.push(targetId)}});
      await activateTarget(cardTargetForMode('smart-plug'), {{activateInteraction: async (targetId) => interactions.push(targetId)}});
      const result = {{
        empty: formatReading(null, 'W'),
        on: commandForPower(true),
        off: commandForPower('off'),
        snapshot: statesFromEvent({{kind: 'snapshot', data: {{states: [{{capability_id: 'switch', value: true}}]}}}}),
        point: statesFromEvent({{kind: 'point', data: {{capabilityId: 'energy_power', value: 12.5, unit: 'W'}}}}),
        interactions,
        compactDensity: dashboardDensity({{}}),
        expandedDensity: dashboardDensity({{dashboard_density: 'expanded'}}),
      }};
      process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["empty"] == "—"
    assert result["on"] == "turn_off"
    assert result["off"] == "turn_on"
    assert result["snapshot"][0]["capability_id"] == "switch"
    assert result["point"][0]["capability_id"] == "energy_power"
    assert result["interactions"] == ["device-card", "smart-plug-card"]
    assert result["compactDensity"] == "compact"
    assert result["expandedDensity"] == "expanded"


def test_signed_build_is_deterministic_and_contains_assets_once(tmp_path: Path) -> None:
    first_archive, first_manifest = build(
        tmp_path / "first", check=True, env_name="unused", key_id="test-key"
    )
    second_archive, _ = build(
        tmp_path / "second", check=True, env_name="unused", key_id="test-key"
    )
    assert first_archive.read_bytes() == second_archive.read_bytes()
    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert manifest["artifact"]["digest"] == (
        f"sha256:{hashlib.sha256(first_archive.read_bytes()).hexdigest()}"
    )
    with ZipFile(first_archive) as package:
        assert package.namelist() == [
            "package.source.json",
            "assets/kasa-widget.mjs",
            "themes/kasa.css",
            "themes/quiet.css",
        ]


def test_built_manifest_validates_against_checked_out_core_contract(tmp_path: Path) -> None:
    contract_path = ROOT.parent / "PiPhi-Network-Core" / "src" / "piphi_network_core" / "widgets" / "package_contract.py"
    if not contract_path.is_file():
        pytest.skip("PiPhi-Network-Core is not checked out beside the integration")
    spec = importlib.util.spec_from_file_location("kasa_core_widget_contract", contract_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _, manifest_path = build(tmp_path, check=True, env_name="unused", key_id="test-key")
    parsed = module.InstalledWidgetPackageManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert len(parsed.widgets) == 4
