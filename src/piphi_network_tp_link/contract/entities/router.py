from fastapi import APIRouter

from piphi_network_tp_link.lib.manifest import load_manifest

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def get_entities() -> dict:
    manifest = load_manifest()
    return {
        "entities": manifest.get("entities", []),
        "capabilities": manifest.get("capabilities", {}),
        "commands": manifest.get("commands", {}),
    }
