from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
import re
import unicodedata

from openpyxl import Workbook, load_workbook
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "customers"
FIELDS = (
    "company_name",
    "contact_person",
    "address",
    "phone_number",
    "website",
    "facebook",
    "zalo",
    "notes",
)


class CustomerNotFoundError(LookupError):
    pass


class CustomerImportError(ValueError):
    pass


TEMPLATE_HEADERS = (
    "Tên công ty",
    "Điện thoại",
    "Người liên hệ",
)

HEADER_ALIASES = {
    "company_name": {
        "ten cong ty",
        "company name",
        "company",
        "cong ty",
    },
    "phone_number": {
        "dien thoai",
        "so dien thoai",
        "phone",
        "phone number",
        "sdt",
        "tel",
        "mobile",
    },
    "contact_person": {
        "nguoi lien he",
        "nguoi lien lac",
        "contact",
        "contact person",
        "lien he",
    },
}

INSERT_CHUNK_SIZE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_interactions(items: list | None) -> list[dict]:
    normalized = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        content = _text(item.get("content"))
        if not content:
            continue
        created_at = item.get("created_at")
        if created_at is None:
            created_at = _now()
        elif hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        else:
            created_at = str(created_at)
        interaction_id = item.get("id") or uuid4()
        normalized.append(
            {
                "id": str(interaction_id),
                "content": content,
                "created_at": created_at,
            }
        )
    return normalized


def _to_row(payload: dict, clerk_id: str, *, include_history: bool) -> dict:
    row = {field: _text(payload.get(field)) for field in FIELDS}
    row["clerk_id"] = clerk_id
    if include_history:
        row["interaction_history"] = _normalize_interactions(
            payload.get("interaction_history")
        )
    return row


def _owned_query(customer_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select("*")
        .eq("id", customer_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _fold_header(value: str) -> str:
    text = value.strip().lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _map_headers(headers: tuple) -> dict[int, str]:
    mapping = {}
    for index, header in enumerate(headers):
        folded = _fold_header(_cell_text(header))
        if not folded:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if folded in aliases:
                mapping[index] = field
                break
    return mapping


def _row_payload(values: tuple, mapping: dict[int, str]) -> dict:
    payload = {field: "" for field in FIELDS}
    for index, field in mapping.items():
        if index >= len(values):
            continue
        payload[field] = _cell_text(values[index])
    return payload


def _is_empty_payload(payload: dict) -> bool:
    return not any(_text(payload.get(field)) for field in FIELDS)


def create_customers(clerk_id: str, payloads: list[dict]) -> list[dict]:
    if not payloads:
        return []
    ensure_user(clerk_id)
    saved = []
    for start in range(0, len(payloads), INSERT_CHUNK_SIZE):
        chunk = [
            _to_row(item, clerk_id, include_history=True)
            for item in payloads[start : start + INSERT_CHUNK_SIZE]
        ]
        result = supabase.table(TABLE).insert(chunk).execute()
        saved.extend(result.data or [])
    return saved


def import_customers_from_xlsx(clerk_id: str, content: bytes) -> dict:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise CustomerImportError("File Excel không hợp lệ.") from exc

    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration as exc:
            raise CustomerImportError("File Excel trống.") from exc

        mapping = _map_headers(headers or ())
        if not mapping:
            raise CustomerImportError(
                "Không nhận diện được cột. Hãy dùng file mẫu (Tên công ty, Điện thoại, Người liên hệ)."
            )

        payloads = []
        skipped = 0
        for values in rows:
            values = values or ()
            if all(value is None or str(value).strip() == "" for value in values):
                skipped += 1
                continue
            payload = _row_payload(values, mapping)
            if _is_empty_payload(payload):
                skipped += 1
                continue
            payloads.append(payload)
    finally:
        workbook.close()

    saved = create_customers(clerk_id, payloads)
    return {
        "imported": len(saved),
        "skipped": skipped,
        "customers": saved,
    }


def build_customer_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Khach hang"
    sheet.append(list(TEMPLATE_HEADERS))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def create_customer(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(TABLE)
        .insert(_to_row(payload, clerk_id, include_history=True))
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create customer")
    return result.data[0]


def list_customers(clerk_id: str) -> list[dict]:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_customer(customer_id: str, clerk_id: str) -> dict:
    result = _owned_query(customer_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise CustomerNotFoundError("Customer not found")
    return data[0]


def update_customer(customer_id: str, clerk_id: str, payload: dict) -> dict:
    get_customer(customer_id, clerk_id)

    updates = {}
    for field in FIELDS:
        if field in payload and payload[field] is not None:
            updates[field] = _text(payload[field])
    if "interaction_history" in payload and payload["interaction_history"] is not None:
        updates["interaction_history"] = _normalize_interactions(
            payload["interaction_history"]
        )
    if not updates:
        return get_customer(customer_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", customer_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise CustomerNotFoundError("Customer not found")
    return result.data[0]


def delete_customer(customer_id: str, clerk_id: str) -> dict:
    existing = get_customer(customer_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", customer_id).eq(
        "clerk_id", clerk_id
    ).execute()
    return existing
