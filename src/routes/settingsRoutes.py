from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.settings import (
    RAG_STRATEGIES,
    get_rag_settings,
    get_settings,
    update_rag_settings,
    update_settings,
)

router = APIRouter(tags=["settingsRoutes"])


class UpdateSettingsRequest(BaseModel):
    default_payment_term_days: int = Field(ge=0)


class UpdateRagSettingsRequest(BaseModel):
    rag_strategy: str
    final_context_size: int = Field(ge=1, le=30)
    similarity_threshold: float = Field(ge=0, le=1)
    chunks_per_search: int = Field(ge=1, le=30)
    vector_weight: float = Field(ge=0, le=1)
    keyword_weight: float = Field(ge=0, le=1)
    number_of_queries: int = Field(ge=1, le=6)


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


@router.get("/rag")
async def read_rag_settings(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_rag_settings(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load RAG settings: {str(e)}",
        )


@router.patch("/rag")
async def edit_rag_settings(
    body: UpdateRagSettingsRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    if body.rag_strategy not in RAG_STRATEGIES:
        raise HTTPException(status_code=400, detail="rag_strategy is not supported")
    try:
        return update_rag_settings(user_clerk_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update RAG settings: {str(e)}",
        )
