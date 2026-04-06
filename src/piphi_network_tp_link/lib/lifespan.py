import contextlib

from fastapi import FastAPI
from httpx import AsyncClient
from piphi_runtime_kit_python import build_runtime_auth_headers, runtime_lifespan

from piphi_network_tp_link.contract.config.routes import (
    apply_runtime_config_snapshot,
)
from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import RuntimeConfigSnapshot, TPLinkDeviceConfig
from piphi_network_tp_link.lib.store import get_runtime_context

CORE_BASE_URL = "http://127.0.0.1:31419"
CORE_REQUEST_TIMEOUT_SECONDS = 10.0
runtime_context = get_runtime_context()


async def call_core_for_devices(
    client: AsyncClient,
    *,
    container_id: str,
    internal_token: str,
) -> None:
    response = await client.get(
        f"{CORE_BASE_URL}/api/v2/integrations/config/fetch/all/by/container/internal",
        params={"container_id": container_id},
        headers=build_runtime_auth_headers(
            container_id=container_id,
            internal_token=internal_token,
        ),
        timeout=CORE_REQUEST_TIMEOUT_SECONDS,
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


async def startup_sync(_runtime_context, core_http_client: AsyncClient) -> None:
    container_id = runtime_context.auth.container_id
    internal_token = runtime_context.auth.internal_token

    if internal_token and container_id:
        await call_core_for_devices(
            core_http_client,
            container_id=container_id,
            internal_token=internal_token,
        )
    else:
        logger.warning(
            "kasa_startup_missing_runtime_credentials "
            "standalone_mode=true"
        )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("kasa_lifespan_start")
    async with runtime_lifespan(
        runtime_context,
        on_startup=startup_sync,
        core_client_timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    ):
        try:
            yield
        finally:
            logger.info("kasa_lifespan_shutdown")
