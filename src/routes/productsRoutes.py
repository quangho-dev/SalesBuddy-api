from uuid import UUID
import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.products import (
    DuplicateProductCodeError,
    ProductImportError,
    ProductNotFoundError,
    build_product_template,
    create_product,
    delete_product,
    export_products_xlsx,
    get_product,
    import_product_rows,
    import_products_from_xlsx,
    list_products,
    parse_product_workbook,
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


class ProductImportRow(BaseModel):
    row: int = 0
    product: dict = Field(default_factory=dict)
    changes: dict = Field(default_factory=dict)


class ImportProductBatchRequest(BaseModel):
    rows: list[ProductImportRow] = Field(default_factory=list, max_length=80)


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


def _read_import_file(file: UploadFile, content: bytes) -> None:
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx")
    if not content:
        raise HTTPException(status_code=400, detail="File Excel trống")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="File Excel vượt quá 5MB")


@router.post("/import/parse")
async def parse_products_import(
    _user_clerk_id: str = Depends(get_current_user_clerk_id),
    file: UploadFile = File(...),
):
    content = await file.read()
    _read_import_file(file, content)
    try:
        return await asyncio.to_thread(parse_product_workbook, content)
    except ProductImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read product file: {str(e)}",
        )


@router.post("/import/batch")
async def import_products_batch(
    body: ImportProductBatchRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    if not body.rows:
        raise HTTPException(status_code=400, detail="Không có dòng sản phẩm để import.")
    try:
        return await asyncio.to_thread(
            import_product_rows,
            user_clerk_id,
            [row.model_dump() for row in body.rows],
        )
    except ProductImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DuplicateProductCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import products: {str(e)}",
        )


@router.post("/import")
async def import_products(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
    file: UploadFile = File(...),
):
    content = await file.read()
    _read_import_file(file, content)

    try:
        return await asyncio.to_thread(
            import_products_from_xlsx, user_clerk_id, content
        )
    except ProductImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import products: {str(e)}",
        )


@router.get("/export")
async def export_products(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        content = export_products_xlsx(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export products: {str(e)}",
        )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="san-pham.xlsx"'},
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
    except DuplicateProductCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    except DuplicateProductCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
