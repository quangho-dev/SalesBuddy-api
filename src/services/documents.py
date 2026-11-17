import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config.index import appConfig
from src.services.awsS3 import s3_client
from src.services.customers import list_customer_owners
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


def document_owner_scope(clerk_id: str) -> tuple[list[str], dict[str, dict]]:
    """Clerk ids whose documents this user may read, plus display labels.

    A sales manager reads their own documents and those uploaded by sales staff
    in the same organization. A sales representative reads only their own.
    """
    owners = list_customer_owners(clerk_id)
    if not owners:
        return [clerk_id], {}
    labels: dict[str, dict] = {}
    owner_ids: list[str] = []
    for owner in owners:
        owner_id = str(owner.get("clerk_id") or "").strip()
        if not owner_id or owner_id in labels:
            continue
        labels[owner_id] = {
            "name": str(owner.get("name") or "").strip(),
            "email": str(owner.get("email") or "").strip(),
            "is_self": bool(owner.get("is_self")),
        }
        owner_ids.append(owner_id)
    return owner_ids or [clerk_id], labels


def owner_display(name: str, email: str) -> str:
    clean_name = str(name or "").strip()
    clean_email = str(email or "").strip()
    if clean_name and clean_email:
        return f"{clean_name} · {clean_email}"
    return clean_name or clean_email or "Nhân viên chưa có email"


def _public_document(row: dict, viewer_id: str = "", labels: dict | None = None) -> dict:
    owner_id = str(row.get("clerk_id") or "")
    label = (labels or {}).get(owner_id) or {}
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
        "owner_name": str(label.get("name") or "").strip(),
        "owner_email": str(label.get("email") or "").strip(),
        "is_owner": owner_id == viewer_id if viewer_id else True,
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
    owner_ids, labels = document_owner_scope(clerk_id)
    result = (
        supabase.table(DOCUMENTS)
        .select(
            "id, clerk_id, filename, content_type, byte_size, status, source_type, processing_status, error, chunk_count, created_at, updated_at"
        )
        .in_("clerk_id", owner_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return [_public_document(row, clerk_id, labels) for row in result.data or []]


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
    return _public_document(document, clerk_id)


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


def get_visible_document(clerk_id: str, document_id: str) -> dict:
    document_id = _parse_document_id(document_id)
    owner_ids, labels = document_owner_scope(clerk_id)
    result = (
        supabase.table(DOCUMENTS)
        .select("*")
        .eq("id", document_id)
        .in_("clerk_id", owner_ids)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise DocumentNotFoundError("Document not found.")
    return _public_document(rows[0], clerk_id, labels)


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

