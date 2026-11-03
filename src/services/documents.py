import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config.index import appConfig
from src.services.awsS3 import s3_client
from src.services.supabase import supabase
from src.services.users import ensure_user

DOCUMENTS = "sales_documents"
CHUNKS = "sales_document_chunks"
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
_CHUNK_INSERT_BATCH = 40

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class DocumentNotFoundError(LookupError):
    pass


def _parse_document_id(document_id: str) -> str:
    try:
        return str(uuid.UUID(document_id))
    except (TypeError, ValueError):
        raise DocumentNotFoundError("Document not found.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def _safe_filename(filename: str) -> str:
    name = Path(filename or "tai-lieu").name.replace("\x00", "").strip()
    name = re.sub(r"\s+", " ", name)
    if name in {"", ".", ".."}:
        name = "tai-lieu"
    return name[:180]


def _public_document(row: dict) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "byte_size": row["byte_size"],
        "status": row["status"],
        "source_type": row.get("source_type") or "file",
        "processing_status": row.get("processing_status"),
        "error": row.get("error"),
        "chunk_count": row.get("chunk_count") or 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_document_record(document_id: str) -> dict | None:
    result = (
        supabase.table(DOCUMENTS)
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_document(clerk_id: str, document_id: str) -> dict:
    document_id = _parse_document_id(document_id)
    result = (
        supabase.table(DOCUMENTS)
        .select("*")
        .eq("id", document_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise DocumentNotFoundError("Document not found.")
    return _public_document(rows[0])


def list_documents(clerk_id: str) -> list[dict]:
    ensure_user(clerk_id)
    result = (
        supabase.table(DOCUMENTS)
        .select(
            "id, filename, content_type, byte_size, status, source_type, processing_status, error, chunk_count, created_at, updated_at"
        )
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_public_document(row) for row in result.data or []]


def set_document_status(
    document_id: str,
    status: str,
    error: str | None = None,
    chunk_count: int | None = None,
) -> None:
    payload: dict = {"status": status, "error": error, "updated_at": _now()}
    if chunk_count is not None:
        payload["chunk_count"] = chunk_count
    supabase.table(DOCUMENTS).update(payload).eq("id", document_id).execute()


def replace_document_chunks(document_id: str, rows: list[dict]) -> None:
    supabase.table(CHUNKS).delete().eq("document_id", document_id).execute()
    for start in range(0, len(rows), _CHUNK_INSERT_BATCH):
        supabase.table(CHUNKS).insert(rows[start : start + _CHUNK_INSERT_BATCH]).execute()


def enqueue_document_embedding(document_id: str) -> None:
    from src.services.celery import perform_rag_ingestion_task

    perform_rag_ingestion_task.delay(document_id)


def create_document(clerk_id: str, filename: str, data: bytes) -> dict:
    ensure_user(clerk_id)
    safe_name = _safe_filename(filename)
    extension = _file_extension(safe_name)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ file PDF, DOCX, PPTX, TXT và Markdown.")
    if not data:
        raise ValueError("File trống.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("File vượt quá 15 MB.")

    created = (
        supabase.table(DOCUMENTS)
        .insert(
            {
                "clerk_id": clerk_id,
                "filename": safe_name,
                "content_type": CONTENT_TYPES[extension],
                "byte_size": len(data),
                "storage_key": "pending",
                "source_type": "file",
                "status": "pending",
                "processing_status": "pending",
                "processing_details": {},
                "chunk_count": 0,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        .execute()
    )
    document = created.data[0]
    storage_key = f"sales-documents/{clerk_id}/{document['id']}/{safe_name}"
    try:
        s3_client.put_object(
            Bucket=appConfig["s3_bucket_name"],
            Key=storage_key,
            Body=data,
            ContentType=CONTENT_TYPES[extension],
        )
        supabase.table(DOCUMENTS).update(
            {"storage_key": storage_key, "updated_at": _now()}
        ).eq("id", document["id"]).execute()
        document["storage_key"] = storage_key
    except Exception:
        supabase.table(DOCUMENTS).delete().eq("id", document["id"]).execute()
        raise

    try:
        enqueue_document_embedding(document["id"])
    except Exception as exc:
        set_document_status(document["id"], "failed", error=str(exc))
        document["status"] = "failed"
        document["error"] = str(exc)
    return _public_document(document)


def reembed_document(clerk_id: str, document_id: str) -> dict:
    document_id = _parse_document_id(document_id)
    get_document(clerk_id, document_id)
    supabase.table(DOCUMENTS).update(
        {
            "status": "pending",
            "processing_status": "pending",
            "error": None,
            "updated_at": _now(),
        }
    ).eq("id", document_id).eq("clerk_id", clerk_id).execute()
    try:
        enqueue_document_embedding(document_id)
    except Exception as exc:
        set_document_status(document_id, "failed", error=str(exc))
        raise
    return get_document(clerk_id, document_id)


def delete_document(clerk_id: str, document_id: str) -> None:
    document_id = _parse_document_id(document_id)
    result = (
        supabase.table(DOCUMENTS)
        .select("id, storage_key")
        .eq("id", document_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise DocumentNotFoundError("Document not found.")
    storage_key = rows[0]["storage_key"]
    supabase.table(DOCUMENTS).delete().eq("id", document_id).eq("clerk_id", clerk_id).execute()
    if storage_key and storage_key != "pending":
        s3_client.delete_object(Bucket=appConfig["s3_bucket_name"], Key=storage_key)

