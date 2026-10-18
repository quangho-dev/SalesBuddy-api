from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.customers import (
    CustomerNotFoundError,
    create_customer,
    delete_customer,
    get_customer,
    list_customers,
    update_customer,
)

router = APIRouter(tags=["customerRoutes"])


class CustomerInteraction(BaseModel):
    id: UUID | None = None
    content: str = Field(min_length=1)
    created_at: datetime | None = None


class CreateCustomerRequest(BaseModel):
    company_name: str = ""
    contact_person: str = ""
    address: str = ""
    phone_number: str = ""
    website: str = ""
    facebook: str = ""
    zalo: str = ""
    notes: str = ""
    interaction_history: list[CustomerInteraction] = Field(default_factory=list)


class UpdateCustomerRequest(BaseModel):
    company_name: str | None = None
    contact_person: str | None = None
    address: str | None = None
    phone_number: str | None = None
    website: str | None = None
    facebook: str | None = None
    zalo: str | None = None
    notes: str | None = None
    interaction_history: list[CustomerInteraction] | None = None


@router.get("")
@router.get("/")
async def list_all_customers(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_customers(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list customers: {str(e)}",
        )


@router.get("/{customer_id}")
async def get_customer_detail(
    customer_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_customer(str(customer_id), user_clerk_id)
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load customer: {str(e)}",
        )


@router.post("")
@router.post("/")
async def add_customer(
    body: CreateCustomerRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_customer(user_clerk_id, body.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create customer: {str(e)}",
        )


@router.patch("/{customer_id}")
async def edit_customer(
    customer_id: UUID,
    body: UpdateCustomerRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        return update_customer(str(customer_id), user_clerk_id, payload)
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update customer: {str(e)}",
        )


@router.delete("/{customer_id}")
async def remove_customer(
    customer_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        deleted = delete_customer(str(customer_id), user_clerk_id)
        return {"deleted": True, "customer": deleted}
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete customer: {str(e)}",
        )
