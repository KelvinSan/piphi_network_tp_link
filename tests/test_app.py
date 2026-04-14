from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient
from piphi_runtime_testkit_python import (
    assert_event_sent,
    assert_telemetry_sent,
    build_config_payload,
    build_config_snapshot,
    build_runtime_headers,
)

from piphi_network_tp_link.app import app
from piphi_network_tp_link.lib.store import registry, runtime_context

config_module = importlib.import_module("piphi_network_tp_link.contract.config.routes")
command_module = importlib.import_module("piphi_network_tp_link.contract.command.router")
discovery_module = importlib.import_module("piphi_network_tp_link.contract.discovery.discovery")


class _DummyTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


def reset_runtime_state() -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime_context.auth.container_id = ""
    runtime_context.auth.internal_token = ""
    runtime_context.process_state.background_tasks.clear()


def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for background delivery to complete.")


def test_config_apply_sends_tp_link_telemetry_and_event(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(*, host: str, username=None, password=None) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **kwargs: _DummyTask())

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(container_id="runtime-123", internal_token="secret-token")

    with TestClient(app) as client:
        response = client.post("/config", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["config_id"] == "plug-1"

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-1")
        event_request = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.configured",
        )

        telemetry_headers = {key.lower(): value for key, value in telemetry_request.headers.items()}
        event_headers = {key.lower(): value for key, value in event_request.headers.items()}

        assert telemetry_headers["x-container-id"] == "runtime-123"
        assert telemetry_headers["x-piphi-integration-token"] == "secret-token"
        assert event_headers["x-container-id"] == "runtime-123"
        assert event_headers["x-piphi-integration-token"] == "secret-token"
        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2
        assert telemetry_request.json_body["units"]["current_power_w"] == "W"
        assert (event_request.json_body.get("event_type") or event_request.json_body.get("type")) == "device.configured"


def test_config_sync_replaces_tp_link_device_and_uses_testkit_snapshot(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(*, host: str, username=None, password=None) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **kwargs: _DummyTask())

    old_payload = build_config_payload(
        config_id="plug-old",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    new_payload = build_config_payload(
        config_id="plug-new",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.228",
            "alias": "Lamp Plug",
        },
    )
    snapshot = build_config_snapshot(
        configs=[new_payload],
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        generation=6,
    )
    headers = build_runtime_headers(container_id="runtime-123", internal_token="secret-token")

    with TestClient(app) as client:
        first_response = client.post("/config", json=old_payload, headers=headers)
        assert first_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        mock_core.reset()

        sync_response = client.post("/config/sync", json=snapshot, headers=headers)
        assert sync_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 2)

        sync_json = sync_response.json()
        assert sync_json["applied"] == ["plug-new"]
        assert sync_json["removed"] == ["plug-old"]
        assert sync_json["active_config_ids"] == ["plug-new"]
        assert sync_json["generation"] == 6

        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-new")
        configured_event = assert_event_sent(
            mock_core,
            device_id="plug-new",
            config_id="plug-new",
            event_type="device.configured",
        )
        deconfigured_event = assert_event_sent(
            mock_core,
            device_id="plug-old",
            config_id="plug-old",
            event_type="device.deconfigured",
        )

        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2
        assert (configured_event.json_body.get("event_type") or configured_event.json_body.get("type")) == "device.configured"
        assert (deconfigured_event.json_body.get("event_type") or deconfigured_event.json_body.get("type")) == "device.deconfigured"


def test_state_route_refreshes_missing_tp_link_snapshot_with_testkit(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(*, host: str, username=None, password=None) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **kwargs: _DummyTask())

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(container_id="runtime-123", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload, headers=headers)
        assert config_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)

        mock_core.reset()
        registry.state_snapshots.clear()

        state_response = client.get("/state")
        assert state_response.status_code == 200
        assert state_response.json()["device_id"] == "plug-1"
        assert state_response.json()["state"]["current_power_w"] == 8.2

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-1")
        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2


def test_deconfigure_sends_tp_link_event_and_removes_entry(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(*, host: str, username=None, password=None) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **kwargs: _DummyTask())

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(container_id="runtime-123", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload, headers=headers)
        assert config_response.status_code == 200
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        mock_core.reset()

        deconfigure_response = client.post("/deconfigure", json={"config": {"id": "plug-1"}})
        assert deconfigure_response.status_code == 200
        assert deconfigure_response.json()["removed"] is True
        assert registry.get("plug-1") is None

        wait_for(lambda: len(mock_core.event_requests) >= 1)
        event_request = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.deconfigured",
        )
        assert (event_request.json_body.get("event_type") or event_request.json_body.get("type")) == "device.deconfigured"


def test_state_returns_404_when_no_tp_link_device_is_configured() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/state")

    assert response.status_code == 404
    assert response.json()["detail"] == "No configured device found"


def test_deconfigure_requires_config_id_for_tp_link() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/deconfigure", json={"config": {}})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing config id"


def test_tp_link_events_route_round_trip() -> None:
    reset_runtime_state()

    event_payload = {
        "event_type": "tp_link.manual.note",
        "source": "test-suite",
        "payload": {"message": "hello"},
    }

    with TestClient(app) as client:
        ingest_response = client.post("/events", json=event_payload)
        list_response = client.get("/events")

    assert ingest_response.status_code == 200
    assert ingest_response.json()["event"]["event_type"] == "tp_link.manual.note"
    assert list_response.status_code == 200
    assert list_response.json()["events"][-1]["event_type"] == "tp_link.manual.note"


def test_tp_link_command_requires_command_name() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing command"


def test_tp_link_command_returns_404_without_primary_device() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "turn_on"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No configured device found"


def test_tp_link_command_runs_device_command_and_returns_refreshed_state(monkeypatch) -> None:
    reset_runtime_state()

    async def fake_run_command_for_device(*, device_id: str, command: str, args: dict[str, object]):
        return {"ok": True, "command": command, "args": args}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    monkeypatch.setattr(command_module, "run_command_for_device", fake_run_command_for_device)
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        response = client.post(
            "/command",
            json={"command": "turn_on", "device_id": "plug-1", "args": {"transition": 1}},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"]["command"] == "turn_on"
    assert response.json()["state"]["state"]["is_on"] is True


def test_tp_link_config_apply_still_succeeds_when_initial_refresh_fails(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def failing_fetch_device_state(*, host: str, username=None, password=None) -> dict[str, object]:
        raise RuntimeError("device unavailable")

    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", failing_fetch_device_state)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **kwargs: _DummyTask())

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(container_id="runtime-123", internal_token="secret-token")

    with TestClient(app) as client:
        response = client.post("/config", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["config_id"] == "plug-1"
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        configured_event = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.configured",
        )

    assert registry.get("plug-1") is not None
    assert (configured_event.json_body.get("event_type") or configured_event.json_body.get("type")) == "device.configured"


@pytest.mark.parametrize("path", ["/ui", "/ui-config"])
def test_tp_link_ui_aliases_return_schema(path: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"]["title"] == "TP-Link Kasa Configuration"
    assert "host" in payload["schema"]["properties"]
    assert "alias" in payload["schema"]["properties"]


@pytest.mark.parametrize("field_name", ["host", "alias", "username", "password"])
def test_tp_link_ui_schema_contains_expected_fields(field_name: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/ui-config")

    assert response.status_code == 200
    assert field_name in response.json()["schema"]["properties"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/discover"),
        ("get", "/discovery"),
        ("post", "/discover"),
        ("post", "/discovery"),
    ],
)
def test_tp_link_discovery_aliases_return_devices(method: str, path: str, monkeypatch) -> None:
    reset_runtime_state()

    async def fake_discover_devices(username=None, password=None):
        return [{"device_id": "plug-1", "host": "10.0.0.227"}]

    monkeypatch.setattr(discovery_module, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        if method == "get":
            response = client.get(path)
        else:
            response = client.post(path, json={"username": "user", "password": "pass"})

    assert response.status_code == 200
    assert response.json()["devices"][0]["device_id"] == "plug-1"


def test_tp_link_discovery_post_passes_credentials(monkeypatch) -> None:
    reset_runtime_state()
    observed: dict[str, object] = {}

    async def fake_discover_devices(username=None, password=None):
        observed["username"] = username
        observed["password"] = password
        return [{"device_id": "plug-1", "host": "10.0.0.227"}]

    monkeypatch.setattr(discovery_module, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        response = client.post("/discover", json={"username": "user", "password": "pass"})

    assert response.status_code == 200
    assert observed == {"username": "user", "password": "pass"}


def test_tp_link_discovery_returns_500_on_exception(monkeypatch) -> None:
    reset_runtime_state()

    async def failing_discover_devices(username=None, password=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(discovery_module, "discover_devices", failing_discover_devices)

    with TestClient(app) as client:
        response = client.get("/discover")

    assert response.status_code == 500
    assert "Discovery failed: boom" in response.json()["detail"]


def test_tp_link_events_list_is_empty_by_default() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/events")

    assert response.status_code == 200
    assert response.json()["events"] == []


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("tp_link.manual.note", {"message": "hello"}),
        ("tp_link.energy.warning", {"current_power_w": 99.1}),
        ("tp_link.device.ping", {"host": "10.0.0.227"}),
    ],
)
def test_tp_link_events_route_round_trip_variants(event_type: str, payload: dict[str, object]) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        ingest_response = client.post(
            "/events",
            json={
                "event_type": event_type,
                "source": "test-suite",
                "payload": payload,
            },
        )
        list_response = client.get("/events")

    assert ingest_response.status_code == 200
    assert ingest_response.json()["event"]["event_type"] == event_type
    assert list_response.status_code == 200
    assert list_response.json()["events"][-1]["payload"] == payload


@pytest.mark.parametrize("path", ["/health", "/diagnostics"])
def test_tp_link_health_routes_work_without_devices(path: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200


def test_tp_link_health_reports_configured_and_state_counts() -> None:
    reset_runtime_state()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    registry.update_state("plug-1", {"current_power_w": 8.2})

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["metadata"]["devices_configured"] == 1
    assert response.json()["metadata"]["devices_with_state"] == 1


def test_tp_link_diagnostics_reports_device_ids() -> None:
    reset_runtime_state()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    registry.update_state("plug-1", {"current_power_w": 8.2})

    with TestClient(app) as client:
        response = client.get("/diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["configured_device_ids"] == ["plug-1"]
    assert diagnostics["devices_with_state"] == ["plug-1"]


def test_tp_link_entities_route_returns_device_specific_commands() -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "alias": "Kitchen Plug",
            "host": "192.168.1.25",
        },
    )
    registry.update_state(
        "plug-1",
        {
            "capabilities": ["switch", "power", "energy_power", "energy_today", "energy_this_month"],
            "device_type": "DeviceType.Plug",
            "model": "KP115",
            "is_on": True,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        },
    )

    with TestClient(app) as client:
        response = client.get("/entities")

    assert response.status_code == 200
    payload = response.json()
    assert "entities" in payload
    assert "capabilities" in payload
    assert "commands" in payload
    assert len(payload["entities"]) == 1
    entity = payload["entities"][0]
    assert entity["device_class"] == "plug"
    assert entity["entity_type"] == "switch"
    assert [command["id"] for command in entity["available_commands"]] == [
        "toggle",
        "turn_on",
        "turn_off",
        "read_energy",
        "refresh",
    ]
    assert entity["available_commands"][0]["label"] == "Toggle"
    assert entity["available_commands"][3]["label"] == "Refresh Energy"


def test_tp_link_manifest_route_returns_identity_fields() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/manifest.json")

    assert response.status_code == 200
    assert response.json()["id"]
    assert response.json()["name"]
    assert response.json()["version"]


def test_tp_link_state_returns_404_for_unknown_explicit_device() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/state", params={"device_id": "missing-device"})

    assert response.status_code == 404
    assert "No state available" in response.json()["detail"]


def test_tp_link_deconfigure_returns_false_when_device_missing() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/deconfigure", json={"config": {"id": "missing-device"}})

    assert response.status_code == 200
    assert response.json()["removed"] is False


def test_tp_link_command_uses_primary_device_when_device_id_missing(monkeypatch) -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    observed: dict[str, object] = {}

    async def fake_run_command_for_device(*, device_id: str, command: str, args: dict[str, object]):
        observed["device_id"] = device_id
        observed["command"] = command
        return {"ok": True}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    monkeypatch.setattr(command_module, "run_command_for_device", fake_run_command_for_device)
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "turn_on"})

    assert response.status_code == 200
    assert observed["device_id"] == "plug-1"
    assert observed["command"] == "turn_on"


def test_tp_link_command_propagates_device_failure(monkeypatch) -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    from fastapi import HTTPException

    async def failing_run_command_for_device(*, device_id: str, command: str, args: dict[str, object]):
        raise HTTPException(status_code=400, detail="Command failed")

    monkeypatch.setattr(command_module, "run_command_for_device", failing_run_command_for_device)

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "turn_on", "device_id": "plug-1"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Command failed"
