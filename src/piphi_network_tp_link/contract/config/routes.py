import asyncio
import datetime
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from piphi_network_tp_link.lib.kasa_client import execute_device_command, fetch_device_state
from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import (
    DeconfigureConfig,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
    TPLinkDeviceConfig,
)
from piphi_network_tp_link.lib.store import (
    devices,
    get_runtime_auth_context,
    latest_states,
    set_runtime_auth_context,
    update_device_state,
)

config_router = APIRouter(tags=["config"])
current_generation: int | None = None

TELEMETRY_URL = "http://127.0.0.1:31419/api/v2/integrations/telemetry"
POLL_INTERVAL_SECONDS = 10
INTERNAL_TOKEN_ENV_NAME = "PIPHI_INTEGRATION_INTERNAL_TOKEN"


def _mask_token(token: str | None) -> str:
    token = (token or "").strip()
    if not token:
        return "missing"
    if len(token) <= 10:
        return "present"
    return f"{token[:6]}...{token[-4:]}"


def _sync_runtime_auth_from_request(request: Request, payload_container_id: str | None = None) -> None:
    header_container_id = (request.headers.get("X-Container-Id") or "").strip()
    header_token = (request.headers.get("X-PiPhi-Integration-Token") or "").strip()

    set_runtime_auth_context(
        container_id=header_container_id or payload_container_id,
        internal_token=header_token,
    )

    logger.info(
        "runtime_internal_auth "
        f"header_container_id={header_container_id or 'missing'} "
        f"payload_container_id={payload_container_id or 'missing'} "
        f"token={_mask_token(header_token)}"
    )


def _resolve_runtime_auth(container_id: str | None) -> tuple[str, str]:
    runtime_auth = get_runtime_auth_context()
    resolved_container_id = ((container_id or "").strip() or runtime_auth.get("container_id", "").strip())
    resolved_internal_token = (
        runtime_auth.get("internal_token", "").strip()
        or (os.getenv(INTERNAL_TOKEN_ENV_NAME) or "").strip()
    )
    return resolved_container_id, resolved_internal_token


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_telemetry_metrics(telemetry_data: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "is_on": bool(telemetry_data.get("is_on", False)),
        "device_type": telemetry_data.get("device_type"),
        "model": telemetry_data.get("model"),
        "signal_strength": telemetry_data.get("signal_strength"),
    }

    current_power_w = _safe_float(telemetry_data.get("current_power_w"))
    today_kwh = _safe_float(telemetry_data.get("today_kwh"))
    month_kwh = _safe_float(telemetry_data.get("month_kwh"))

    energy = telemetry_data.get("energy") or {}
    if current_power_w is None:
        current_power_w = _safe_float(energy.get("current_power_w"))
    if today_kwh is None:
        today_kwh = _safe_float(energy.get("today_kwh"))
    if month_kwh is None:
        month_kwh = _safe_float(energy.get("month_kwh"))

    if current_power_w is not None:
        metrics["current_power_w"] = current_power_w
    if today_kwh is not None:
        metrics["today_kwh"] = today_kwh
    if month_kwh is not None:
        metrics["month_kwh"] = month_kwh

    return {key: value for key, value in metrics.items() if value is not None}


def _build_telemetry_payload(telemetry_data: dict[str, Any], device_id: str) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "metrics": _build_telemetry_metrics(telemetry_data),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "units": {
            "signal_strength": "dBm",
            "current_power_w": "W",
            "today_kwh": "kWh",
            "month_kwh": "kWh",
        },
    }


async def send_telemetry_to_core(
    telemetry_data: dict[str, Any],
    device_id: str,
    container_id: str | None,
) -> None:
    try:
        resolved_container_id, resolved_internal_token = _resolve_runtime_auth(container_id)
        if not resolved_container_id:
            logger.warning("telemetry_send_skipped reason=missing_container_id")
            return

        headers = {"X-Container-Id": resolved_container_id}
        if resolved_internal_token:
            headers["X-PiPhi-Integration-Token"] = resolved_internal_token

        payload = _build_telemetry_payload(telemetry_data, device_id)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=TELEMETRY_URL,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.RequestError as exc:
        logger.error(f"telemetry_send_request_error error={exc}")
    except httpx.HTTPStatusError as exc:
        logger.error(
            "telemetry_send_http_error "
            f"status={exc.response.status_code} body={exc.response.text}"
        )
    except Exception:
        logger.exception("telemetry_send_unexpected_error")


async def fetch_and_store_state(
    *,
    host: str,
    device_id: str,
    container_id: str | None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    payload = await fetch_device_state(host=host, username=username, password=password)
    latest_state = update_device_state(device_id=device_id, state=payload)
    if container_id:
        await send_telemetry_to_core(
            telemetry_data=payload,
            device_id=device_id,
            container_id=container_id,
        )
    return latest_state


async def run_command_for_device(
    *,
    device_id: str,
    command: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    device = devices.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' is not configured")

    try:
        return await execute_device_command(
            host=device["host"],
            command=command,
            args=args or {},
            username=device.get("username"),
            password=device.get("password"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Command failed: {exc}") from exc


async def trigger_refresh(device_id: str) -> dict[str, Any]:
    device = devices.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' is not configured")

    try:
        return await fetch_and_store_state(
            host=device["host"],
            device_id=device_id,
            container_id=device.get("container_id"),
            username=device.get("username"),
            password=device.get("password"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Refresh failed: {exc}") from exc


async def poll_device_state(
    *,
    host: str,
    device_id: str,
    container_id: str | None,
    username: str | None = None,
    password: str | None = None,
) -> None:
    while True:
        try:
            await fetch_and_store_state(
                host=host,
                device_id=device_id,
                container_id=container_id,
                username=username,
                password=password,
            )
            logger.info(f"state_poll_success device_id={device_id} host={host}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"state_poll_error device_id={device_id} host={host} error={exc}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def remove_device_config(device_id: str) -> bool:
    existing_poll = devices.get(device_id)
    if existing_poll and existing_poll.get("task") and not existing_poll["task"].done():
        existing_poll["task"].cancel()
        try:
            await existing_poll["task"]
        except asyncio.CancelledError:
            pass

    removed = device_id in devices
    devices.pop(device_id, None)
    latest_states.pop(device_id, None)
    return removed


async def apply_device_config(payload: TPLinkDeviceConfig) -> dict[str, Any]:
    runtime_auth = get_runtime_auth_context()
    resolved_container_id = payload.container_id or runtime_auth.get("container_id") or None

    if resolved_container_id:
        set_runtime_auth_context(container_id=resolved_container_id)

    await remove_device_config(payload.id)
    task = asyncio.create_task(
        poll_device_state(
            host=payload.host,
            device_id=payload.id,
            container_id=resolved_container_id,
            username=payload.username,
            password=payload.password,
        )
    )
    devices[payload.id] = {
        "task": task,
        "container_id": resolved_container_id,
        "device_id": payload.id,
        "host": payload.host,
        "alias": payload.alias,
        "username": payload.username,
        "password": payload.password,
    }

    try:
        await trigger_refresh(payload.id)
    except HTTPException as exc:
        logger.warning(f"kasa_initial_refresh_failed device_id={payload.id} detail={exc.detail}")

    return {
        "status": "configured",
        "device_id": payload.id,
        "host": payload.host,
    }


async def apply_runtime_config_snapshot(payload: RuntimeConfigSnapshot) -> RuntimeConfigSyncResponse:
    global current_generation

    incoming_generation = payload.generation
    if (
        incoming_generation is not None
        and current_generation is not None
        and int(incoming_generation) < int(current_generation)
    ):
        return RuntimeConfigSyncResponse(
            status="stale_ignored",
            container_id=payload.container_id,
            reason=payload.reason,
            generation=current_generation,
            applied=[],
            removed=[],
            active_config_ids=list(devices.keys()),
            metadata={
                "stale_generation_ignored": True,
                "incoming_generation": incoming_generation,
                "current_generation": current_generation,
            },
        )

    incoming_ids = {config.id for config in payload.configs}
    active_ids = list(devices.keys())
    removed_ids: list[str] = []
    applied_ids: list[str] = []

    for device_id in active_ids:
        if device_id not in incoming_ids:
            removed = await remove_device_config(device_id)
            if removed:
                removed_ids.append(device_id)

    for config in payload.configs:
        await apply_device_config(config)
        applied_ids.append(config.id)

    if incoming_generation is not None:
        current_generation = int(incoming_generation)

    return RuntimeConfigSyncResponse(
        status="synced",
        container_id=payload.container_id,
        reason=payload.reason,
        generation=current_generation,
        applied=applied_ids,
        removed=removed_ids,
        active_config_ids=list(devices.keys()),
        metadata={
            "applied_count": len(applied_ids),
            "removed_count": len(removed_ids),
            "current_generation": current_generation,
        },
    )


@config_router.post("/config")
async def config(payload: TPLinkDeviceConfig, request: Request) -> dict:
    _sync_runtime_auth_from_request(request, payload.container_id)
    return await apply_device_config(payload)


@config_router.post("/configs/sync", response_model=RuntimeConfigSyncResponse)
async def sync_configs(payload: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    _sync_runtime_auth_from_request(request, payload.container_id)
    return await apply_runtime_config_snapshot(payload)


@config_router.post("/config/sync", response_model=RuntimeConfigSyncResponse)
async def sync_config(payload: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    _sync_runtime_auth_from_request(request, payload.container_id)
    return await apply_runtime_config_snapshot(payload)


@config_router.post("/deconfigure")
async def deconfigure_device(payload: DeconfigureConfig) -> dict:
    device_id = payload.config.get("id")
    if device_id is None:
        raise HTTPException(status_code=400, detail="Missing config id")

    removed = await remove_device_config(device_id)
    if not removed:
        logger.info(f"deconfigure_noop device_id={device_id}")

    return {
        "status": "deconfigured",
        "device_id": device_id,
    }
