from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from src.agents.quote_file_agent import generate_quote_file
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.customers import CustomerNotFoundError
from src.services.googleDrive import QuoteTemplateNotFoundError
from src.services.quotes import (
    QuoteNotFoundError,
    convert_quote_to_order,
    create_quote,
    delete_quote,
    get_quote,
    list_quotes,
    update_quote,
)

router = APIRouter(tags=["quoteRoutes"])


class QuoteItemInput(BaseModel):
    product_name: str = Field(min_length=1)
    unit: str = ""
    quantity: float = 0
    selling_price: float = 0
    vat_invoice: bool = False
    notes: str = ""


class CreateQuoteRequest(BaseModel):
    customer_id: UUID
    notes: str = ""
    items: list[QuoteItemInput] = Field(min_length=1)


class UpdateQuoteRequest(BaseModel):
    customer_id: UUID | None = None
    notes: str | None = None
    items: list[QuoteItemInput] | None = None


class QuoteFileCustomerInput(BaseModel):
    company_name: str | None = None
    contact_person: str = ""
    address: str = ""
    phone_number: str = ""
    tax_code: str = ""
    email: str = ""


class GenerateQuoteFileRequest(BaseModel):
    quote_id: UUID | None = None
    customer: QuoteFileCustomerInput | None = None
    notes: str | None = None
    items: list[QuoteItemInput] | None = None
    quote_number: str | None = None
    quote_date: str | None = None


@router.get("")
@router.get("/")
async def list_all_quotes(
    customer_id: UUID | None = Query(default=None),
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_quotes(
            user_clerk_id,
            customer_id=str(customer_id) if customer_id else None,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list quotes: {str(e)}",
        )


@router.post("/generate-file")
async def generate_quote_spreadsheet(
    body: GenerateQuoteFileRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump()
    if not payload.get("quote_id") and not payload.get("items"):
        raise HTTPException(
            status_code=400,
            detail="quote_id or items is required",
        )
    try:
        return await generate_quote_file(user_clerk_id, payload)
    except QuoteNotFoundError:
        raise HTTPException(status_code=404, detail="Quote not found")
    except QuoteTemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate quote file: {str(e)}",
        )


@router.post("/{quote_id}/convert-to-order")
async def convert_quote_into_order(
    quote_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return convert_quote_to_order(str(quote_id), user_clerk_id)
    except QuoteNotFoundError:
        raise HTTPException(status_code=404, detail="Quote not found")
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert quote to order: {str(e)}",
        )


@router.get("/{quote_id}")
async def get_quote_detail(
    quote_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_quote(str(quote_id), user_clerk_id)
    except QuoteNotFoundError:
        raise HTTPException(status_code=404, detail="Quote not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load quote: {str(e)}",
        )


@router.post("")
@router.post("/")
async def add_quote(
    body: CreateQuoteRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_quote(user_clerk_id, body.model_dump())
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create quote: {str(e)}",
        )


@router.patch("/{quote_id}")
async def edit_quote(
    quote_id: UUID,
    body: UpdateQuoteRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "items" in payload and payload["items"] is not None and not payload["items"]:
        raise HTTPException(status_code=400, detail="at least one item is required")

    try:
        return update_quote(str(quote_id), user_clerk_id, payload)
    except QuoteNotFoundError:
        raise HTTPException(status_code=404, detail="Quote not found")
    except CustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Customer not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update quote: {str(e)}",
        )


@router.delete("/{quote_id}")
async def remove_quote(
    quote_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        deleted = delete_quote(str(quote_id), user_clerk_id)
        return {"deleted": True, "quote": deleted}
    except QuoteNotFoundError:
        raise HTTPException(status_code=404, detail="Quote not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete quote: {str(e)}",
        )
