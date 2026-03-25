from fastapi import APIRouter

from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import EventRequest
from piphi_network_tp_link.lib.store import append_event, recent_events

router = APIRouter(tags=["events"])


@router.get("/events")
async def get_events() -> dict:
    logger.info(f"events_list count={len(recent_events)}")
    return {"events": recent_events}


@router.post("/events")
async def ingest_event(payload: EventRequest) -> dict:
    event = append_event(payload.model_dump())
    logger.info(
        "event_ingested "
        f"event_type={payload.event_type} "
        f"source={payload.source or 'unknown'}"
    )
    return {
        "status": "accepted",
        "event": event,
    }
