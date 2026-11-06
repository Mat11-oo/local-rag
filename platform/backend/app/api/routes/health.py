from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session
from ...schemas import HealthResponse

router = APIRouter()


async def database_health(session: AsyncSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    settings = get_settings()
    database_status = await database_health(session)
    payload = HealthResponse(
        service=settings.app_name,
        environment=settings.env,
        database=database_status,
    )
    return JSONResponse(
        status_code=200 if database_status == "ok" else 503,
        content=payload.model_dump(mode="json"),
    )


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    database_status = await database_health(session)
    return JSONResponse(
        status_code=200 if database_status == "ok" else 503,
        content={"status": "ok" if database_status == "ok" else "error", "database": database_status},
    )

