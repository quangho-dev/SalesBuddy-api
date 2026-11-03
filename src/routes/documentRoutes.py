from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from src.rag.retrieval.index import retrieve_context
from src.rag.retrieval.utils import prepare_prompt_and_invoke_llm
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentNotFoundError,
    create_document,
    delete_document,
    get_document,
    list_documents,
    reembed_document,
)

router = APIRouter(tags=["documentRoutes"])


class QueryDocumentsRequest(BaseModel):
    query: str = Field(..., min_length=2)
    limit: int = Field(8, ge=1, le=20)


def _error_text(exc: BaseException) -> str:
    exceptions = getattr(exc, "exceptions", None)
    if exceptions:
        return "; ".join(_error_text(item) for item in exceptions)
    return str(exc)


@router.get("")
@router.get("/")
async def list_all_documents(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return {"documents": list_documents(user_clerk_id)}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list documents: {_error_text(exc)}",
        )


@router.post("/query")
async def query_documents(
    body: QueryDocumentsRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        texts, images, tables, citations = retrieve_context(
            user_clerk_id,
            body.query,
            limit=body.limit,
        )
        if not texts and not tables and not images:
            answer = "Không tìm thấy nội dung liên quan trong tài liệu đã tải."
        else:
            answer = prepare_prompt_and_invoke_llm(body.query, texts, images, tables)
        return {
            "answer": answer,
            "texts": texts,
            "tables": tables,
            "images": images,
            "citations": citations,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query documents: {_error_text(exc)}",
        )


@router.post("")
@router.post("/")
async def upload_document(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
    file: UploadFile = File(...),
):
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        document = create_document(user_clerk_id, file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload document: {_error_text(exc)}",
        )
    return document


@router.get("/{document_id}")
async def read_document(
    document_id: str,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_document(user_clerk_id, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load document: {_error_text(exc)}",
        )


@router.post("/{document_id}/embed")
async def embed_document(
    document_id: str,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return reembed_document(user_clerk_id, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to embed document: {_error_text(exc)}",
        )


@router.delete("/{document_id}")
async def remove_document(
    document_id: str,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        delete_document(user_clerk_id, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document: {_error_text(exc)}",
        )
    return {"deleted": True}
