from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.customers import CustomerNotFoundError
from src.services.orders import (
    OrderNotFoundError,
    create_order,
    delete_order,
    get_order,
    list_orders,
    update_order,
)

router = APIRouter(tags=["orderRoutes"])


class OrderItemInput(BaseModel):
    product_name: str = Field(min_length=1)
    unit: str = ""
    quantity: float = 0
    selling_price: float = 0
    vat_invoice: bool = False
    notes: str = ""


class CreateOrderRequest(BaseModel):
    customer_id: UUID
    order_date: date | None = None
    notes: str = ""
    items: list[OrderItemInput] = Field(min_length=1)


class UpdateOrderRequest(BaseModel):
    customer_id: UUID | None = None
    order_date: date | None = None
    notes: str | None = None
    items: list[OrderItemInput] | None = None


@router.get("")
@router.get("/")
async def list_all_orders(
    customer_id: UUID | None = Query(default=None),
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_orders(
            user_clerk_id,
            customer_id=str(customer_id) if customer_id else None,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list orders: {str(e)}",
        )


@router.get("/{order_id}")
async def get_order_detail(
    order_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_order(str(order_id), user_clerk_id)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load order: {str(e)}",
        )


@router.post("")
@router.post("/")
async def add_order(
    body: CreateOrderRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_order(user_clerk_id, body.model_dump())
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create order: {str(e)}",
        )


@router.patch("/{order_id}")
async def edit_order(
    order_id: UUID,
    body: UpdateOrderRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "items" in payload and payload["items"] is not None and not payload["items"]:
        raise HTTPException(status_code=400, detail="at least one item is required")

    try:
        return update_order(str(order_id), user_clerk_id, payload)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update order: {str(e)}",
        )


@router.delete("/{order_id}")
async def remove_order(
    order_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        deleted = delete_order(str(order_id), user_clerk_id)
        return {"deleted": True, "order": deleted}
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete order: {str(e)}",
        )
