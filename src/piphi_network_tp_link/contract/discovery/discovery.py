from fastapi import APIRouter, HTTPException

from piphi_network_tp_link.lib.kasa_client import discover_devices


router = APIRouter(tags=["discovery"])


@router.get("/discover")
@router.get("/discovery")
async def get_discovered_devices() -> dict:
    try:
        devices = await discover_devices()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Discovery failed: {exc}") from exc
    return {"devices": devices}
