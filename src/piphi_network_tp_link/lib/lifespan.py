import contextlib
import os

from fastapi import FastAPI
from httpx import AsyncClient

from piphi_network_tp_link.contract.config.routes import apply_runtime_config_snapshot
from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import RuntimeConfigSnapshot, TPLinkDeviceConfig
from piphi_network_tp_link.lib.store import set_runtime_auth_context

CORE_BASE_URL = "http://127.0.0.1:31419"
RUNTIME_CONTAINER_ID_ENV_NAME = "PIPHI_CONTAINER_ID"
RUNTIME_INTERNAL_TOKEN_ENV_NAME = "PIPHI_INTEGRATION_INTERNAL_TOKEN"


async def call_core_for_devices(container_id: str, internal_token: str) -> None:
    async with AsyncClient() as client:
        response = await client.get(
            f"{CORE_BASE_URL}/api/v2/integrations/config/fetch/all/by/container/internal",
            params={"container_id": container_id},
            headers={
                "X-Container-Id": container_id,
                "X-PiPhi-Integration-Token": internal_token,
            },
        )
        response.raise_for_status()

    data = response.json()
    if not data:
        logger.info("kasa_startup_rehydrate_no_configs")
        return

    snapshot = RuntimeConfigSnapshot(
        container_id=container_id,
        reason="startup_rehydrate",
        configs=[TPLinkDeviceConfig(**item["config_data"], container_id=container_id) for item in data],
    )
    await apply_runtime_config_snapshot(snapshot)
    logger.info(f"kasa_startup_rehydrate_complete loaded={len(data)}")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("kasa_lifespan_start")

    container_id = (os.getenv(RUNTIME_CONTAINER_ID_ENV_NAME) or "").strip()
    internal_token = (os.getenv(RUNTIME_INTERNAL_TOKEN_ENV_NAME) or "").strip()

    set_runtime_auth_context(
        container_id=container_id,
        internal_token=internal_token,
    )

    if internal_token and container_id:
        await call_core_for_devices(container_id=container_id, internal_token=internal_token)
    else:
        logger.warning(
            "kasa_startup_missing_runtime_credentials "
            "standalone_mode=true"
        )

    yield

    logger.info("kasa_lifespan_shutdown")
