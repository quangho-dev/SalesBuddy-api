from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.deliveries import (
    DeliveryError,
    DeliveryNotFoundError,
    cancel_delivery,
    get_delivery,
    get_settings,
    list_deliveries,
    place_delivery,
    quote_delivery,
    receive_lalamove_webhook,
    refresh_delivery,
    update_settings,
)

router = APIRouter(tags=["deliveryRoutes"])
settings_router = APIRouter(tags=["deliverySettingsRoutes"])


class DeliverySettingsRequest(BaseModel):
    pickup_name: str = ""
    pickup_phone: str = ""
    pickup_address: str = ""
    pickup_lat: float | None = None
    pickup_lng: float | None = None
    market: str = "VN"
    default_service_type: str = "MOTORCYCLE"


class QuoteDeliveryRequest(BaseModel):
    order_id: UUID
    service_type: str = ""
    schedule_at: str | None = None
    dropoff_lat: float
    dropoff_lng: float


class PlaceDeliveryRequest(BaseModel):
    delivery_id: UUID


class CancelDeliveryRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


@settings_router.get("")
@settings_router.get("/")
async def read_delivery_settings(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_settings(user_clerk_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load delivery settings: {exc}")


@settings_router.patch("")
@settings_router.patch("/")
async def edit_delivery_settings(
    body: DeliverySettingsRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return update_settings(user_clerk_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update delivery settings: {exc}")


@router.get("")
@router.get("/")
async def read_deliveries(
    order_id: UUID | None = None,
    status: str | None = None,
    customer_id: UUID | None = None,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_deliveries(
            user_clerk_id,
            str(order_id) if order_id else None,
            status,
            str(customer_id) if customer_id else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list deliveries: {exc}")


@router.post("/quotations")
async def create_delivery_quotation(
    body: QuoteDeliveryRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return quote_delivery(user_clerk_id, body.model_dump())
    except DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to quote delivery: {exc}")


@router.post("")
@router.post("/")
async def create_delivery(
    body: PlaceDeliveryRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return place_delivery(user_clerk_id, str(body.delivery_id))
    except DeliveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to place delivery: {exc}")


@router.post("/webhooks/lalamove")
async def lalamove_webhook(payload: dict = Body(...)):
    try:
        return receive_lalamove_webhook(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to handle webhook: {exc}")


@router.get("/{delivery_id}")
async def read_delivery(
    delivery_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_delivery(str(delivery_id), user_clerk_id)
    except DeliveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load delivery: {exc}")


@router.post("/{delivery_id}/cancel")
async def cancel_delivery_route(
    delivery_id: UUID,
    body: CancelDeliveryRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return cancel_delivery(user_clerk_id, str(delivery_id), body.reason)
    except DeliveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cancel delivery: {exc}")


@router.post("/{delivery_id}/refresh")
async def refresh_delivery_route(
    delivery_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return refresh_delivery(user_clerk_id, str(delivery_id))
    except DeliveryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to refresh delivery: {exc}")
