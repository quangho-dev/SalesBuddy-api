from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from src.agents.order_file_agent import generate_order_file
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.customers import CustomerNotFoundError
from src.services.googleDrive import QuoteTemplateNotFoundError
from src.services.orders import (
    OrderNotFoundError,
    create_order,
    delete_order,
    get_order,
    list_orders,
    update_order,
)

router = APIRouter(tags=["orderRoutes"])

PaymentMethod = Literal["cash", "bank_transfer"]


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
    is_paid: bool = False
    is_delivered: bool = False
    delivered_at: datetime | None = None
    payment_method: PaymentMethod | None = None
    paid_amount: float = Field(default=0, ge=0)
    items: list[OrderItemInput] = Field(min_length=1)


class UpdateOrderRequest(BaseModel):
    customer_id: UUID | None = None
    order_date: date | None = None
    notes: str | None = None
    is_paid: bool | None = None
    is_delivered: bool | None = None
    delivered_at: datetime | None = None
    payment_method: PaymentMethod | None = None
    paid_amount: float | None = Field(default=None, ge=0)
    items: list[OrderItemInput] | None = None


class OrderFileCustomerInput(BaseModel):
    company_name: str | None = None
    contact_person: str = ""
    address: str = ""
    phone_number: str = ""
    tax_code: str = ""
    email: str = ""


class GenerateOrderFileRequest(BaseModel):
    order_id: UUID | None = None
    customer: OrderFileCustomerInput | None = None
    notes: str | None = None
    items: list[OrderItemInput] | None = None
    order_number: str | None = None
    order_date: str | None = None


@router.get("")
@router.get("/")
async def list_all_orders(
    customer_id: UUID | None = Query(default=None),
    is_paid: bool | None = Query(default=None),
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_orders(
            user_clerk_id,
            customer_id=str(customer_id) if customer_id else None,
            is_paid=is_paid,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list orders: {str(e)}",
        )


@router.post("/generate-file")
async def generate_order_spreadsheet(
    body: GenerateOrderFileRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump()
    if not payload.get("order_id") and not payload.get("items"):
        raise HTTPException(
            status_code=400,
            detail="order_id or items is required",
        )
    try:
        return await generate_order_file(user_clerk_id, payload)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except QuoteTemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate order file: {str(e)}",
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
