from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.orders import OrderNotFoundError
from src.services.payments import (
    PaymentNotFoundError,
    create_payment,
    delete_payment,
    get_payment,
    list_payments,
    update_payment,
)

router = APIRouter(tags=["paymentRoutes"])

PaymentMethod = Literal["cash", "bank_transfer"]


class CreatePaymentRequest(BaseModel):
    order_id: UUID
    amount: float = Field(gt=0)
    payment_date: date | None = None
    payment_method: PaymentMethod


class UpdatePaymentRequest(BaseModel):
    order_id: UUID | None = None
    amount: float | None = Field(default=None, gt=0)
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None


@router.get("")
@router.get("/")
async def list_all_payments(
    order_id: UUID | None = Query(default=None),
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_payments(
            user_clerk_id,
            order_id=str(order_id) if order_id else None,
        )
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list payments: {str(e)}",
        )


@router.get("/{payment_id}")
async def get_payment_detail(
    payment_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_payment(str(payment_id), user_clerk_id)
    except PaymentNotFoundError:
        raise HTTPException(status_code=404, detail="Payment not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load payment: {str(e)}",
        )


@router.post("")
@router.post("/")
async def add_payment(
    body: CreatePaymentRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_payment(user_clerk_id, body.model_dump())
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create payment: {str(e)}",
        )


@router.patch("/{payment_id}")
async def edit_payment(
    payment_id: UUID,
    body: UpdatePaymentRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        return update_payment(str(payment_id), user_clerk_id, payload)
    except PaymentNotFoundError:
        raise HTTPException(status_code=404, detail="Payment not found")
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update payment: {str(e)}",
        )


@router.delete("/{payment_id}")
async def remove_payment(
    payment_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        deleted = delete_payment(str(payment_id), user_clerk_id)
        return {"deleted": True, "payment": deleted}
    except PaymentNotFoundError:
        raise HTTPException(status_code=404, detail="Payment not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete payment: {str(e)}",
        )
