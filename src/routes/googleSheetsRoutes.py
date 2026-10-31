from fastapi import APIRouter, Depends, HTTPException
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.googleSheetsAuth import sheets_connection_status, start_sheets_login

router = APIRouter(tags=["googleSheetsRoutes"])


@router.get("/status")
async def google_sheets_status(
    _user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    return sheets_connection_status()


@router.post("/connect")
async def google_sheets_connect(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return {"url": start_sheets_login(user_clerk_id)}
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Chưa có file OAuth của Google trên server.",
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Không tạo được link đăng nhập Google Sheets.",
        )
