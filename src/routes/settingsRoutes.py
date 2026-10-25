from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.settings import get_settings, update_settings

router = APIRouter(tags=["settingsRoutes"])


class UpdateSettingsRequest(BaseModel):
    default_payment_term_days: int = Field(ge=0)


@router.get("")
@router.get("/")
async def read_settings(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_settings(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load settings: {str(e)}",
        )


@router.patch("")
@router.patch("/")
async def edit_settings(
    body: UpdateSettingsRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return update_settings(user_clerk_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update settings: {str(e)}",
        )
