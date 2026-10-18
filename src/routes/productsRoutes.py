from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.products import (
    ProductImportError,
    ProductNotFoundError,
    build_product_template,
    create_product,
    delete_product,
    get_product,
    import_products_from_xlsx,
    list_products,
    update_product,
)

MAX_IMPORT_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["productsRoutes"])


class CreateProductRequest(BaseModel):
    product_code: str = ""
    name: str = ""
    product_type: str = ""
    unit: str = ""
    selling_price: float = 0
    stock: float = 0
    notes: str = ""


class UpdateProductRequest(BaseModel):
    product_code: str | None = None
    name: str | None = None
    product_type: str | None = None
    unit: str | None = None
    selling_price: float | None = None
    stock: float | None = None
    notes: str | None = None


@router.get("")
@router.get("/")
async def list_all_products(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_products(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list products: {str(e)}",
        )


@router.get("/template")
async def download_product_template(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    content = build_product_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="mau-san-pham.xlsx"'
        },
    )


@router.post("/import")
async def import_products(
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
        return import_products_from_xlsx(user_clerk_id, content)
    except ProductImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import products: {str(e)}",
        )


@router.get("/{product_id}")
async def get_product_detail(
    product_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_product(str(product_id), user_clerk_id)
    except ProductNotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load product: {str(e)}",
        )


@router.post("")
@router.post("/")
async def add_product(
    body: CreateProductRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_product(user_clerk_id, body.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create product: {str(e)}",
        )


@router.patch("/{product_id}")
async def edit_product(
    product_id: UUID,
    body: UpdateProductRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        return update_product(str(product_id), user_clerk_id, payload)
    except ProductNotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update product: {str(e)}",
        )


@router.delete("/{product_id}")
async def remove_product(
    product_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        deleted = delete_product(str(product_id), user_clerk_id)
        return {"deleted": True, "product": deleted}
    except ProductNotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete product: {str(e)}",
        )
