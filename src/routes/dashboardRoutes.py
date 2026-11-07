from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.dashboard import get_dashboard

router = APIRouter(tags=["dashboardRoutes"])

Period = Literal["day", "week", "month", "year"]


@router.get("")
@router.get("/")
async def read_dashboard(
    period: Period = Query(default="month"),
    limit: int = Query(default=5, ge=1, le=20),
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_dashboard(user_clerk_id, period, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load dashboard: {str(error)}",
        )
