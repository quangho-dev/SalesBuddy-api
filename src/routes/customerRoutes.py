from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.customers import (
    CustomerImportError,
    CustomerNotFoundError,
    build_customer_template,
    create_customer,
    delete_customer,
    get_customer,
    import_customers_from_xlsx,
    list_customers,
    update_customer,
)

MAX_IMPORT_BYTES = 5 * 1024 * 1024

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
    tax_code: str = ""
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
    tax_code: str | None = None
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


@router.get("/template")
async def download_customer_template(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    content = build_customer_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="mau-khach-hang.xlsx"'
        },
    )


@router.post("/import")
async def import_customers(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
    file: UploadFile = File(...),
):
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File Excel trống")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="File Excel vượt quá 5MB")

    try:
        return import_customers_from_xlsx(user_clerk_id, content)
    except CustomerImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import customers: {str(e)}",
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
