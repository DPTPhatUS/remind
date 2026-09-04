import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.router import api_router  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.logging import configure_logging  # noqa: E402
from db.models import Patient  # noqa: E402
from db.session import AsyncSessionLocal  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Patient).limit(1))
        if result.scalars().first() is None:
            session.add(
                Patient(
                    display_name="Patient",
                    preferences={},
                    accessibility_settings={},
                )
            )
            await session.commit()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.environment)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()