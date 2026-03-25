from fastapi import APIRouter, HTTPException

from piphi_network_tp_link.contract.config.routes import run_command_for_device, trigger_refresh
from piphi_network_tp_link.lib.schemas import CommandRequest
from piphi_network_tp_link.lib.store import get_primary_device

router = APIRouter(tags=["command"])


@router.post("/command")
async def execute_command(payload: CommandRequest) -> dict:
    command = (payload.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Missing command")

    device_id = payload.device_id
    if device_id is None:
        primary_device = get_primary_device()
        if primary_device is None:
            raise HTTPException(status_code=404, detail="No configured device found")
        device_id = primary_device["device_id"]

    command_result = await run_command_for_device(
        device_id=device_id,
        command=command,
        args=payload.args,
    )

    refreshed_state = await trigger_refresh(device_id)
    return {
        "status": "ok",
        "command": command,
        "device_id": device_id,
        "result": command_result,
        "state": refreshed_state,
    }
