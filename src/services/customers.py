from datetime import datetime, timezone
from uuid import uuid4

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
