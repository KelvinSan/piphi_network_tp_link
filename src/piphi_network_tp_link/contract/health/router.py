from fastapi import APIRouter

from piphi_network_tp_link.lib.manifest import load_manifest
from piphi_network_tp_link.lib.store import devices, latest_states

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_report() -> dict:
    manifest = load_manifest()
    return {
        "status": "ok",
        "integration": {
            "id": manifest["id"],
            "name": manifest["name"],
            "version": manifest["version"],
        },
        "devices_configured": len(devices),
        "devices_with_state": len(latest_states),
    }
