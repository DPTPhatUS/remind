from fastapi import APIRouter

from api.routes import (
    events,
    health,
    interactions,
    live,
    media,
    memories,
    patients,
    people,
    relationships,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(patients.router, prefix="/patients", tags=["patients"])
api_router.include_router(people.router, prefix="/people", tags=["people"])
api_router.include_router(relationships.router, prefix="/relationships", tags=["relationships"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(interactions.router, prefix="/interactions", tags=["interactions"])
api_router.include_router(memories.router, prefix="/memories", tags=["memories"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
api_router.include_router(live.router, prefix="/live", tags=["live"])
