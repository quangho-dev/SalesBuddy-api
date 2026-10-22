from datetime import date, datetime, timezone

from src.services.customers import CustomerNotFoundError, get_customer
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "orders"
ITEMS_TABLE = "order_items"
CUSTOMER_EMBED = "id, company_name, contact_person, phone_number"
SELECT_FIELDS = f"*, customers({CUSTOMER_EMBED}), order_items(*)"
ITEM_FIELDS = (
    "id",
    "product_name",
    "unit",
    "quantity",
    "selling_price",
    "vat_invoice",
    "notes",
)


class OrderNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value) -> float:
    if value is None or value == "":
        return 0
    return float(value)


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "co")
    return bool(value)


def _date(value) -> str:
    if value is None or value == "":
        return date.today().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _owned_customer(customer_id: str, clerk_id: str) -> dict:
    return get_customer(customer_id, clerk_id)


def _normalize_items(items) -> list[dict]:
    if items is None:
        raise ValueError("items is required")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    if not items:
        raise ValueError("at least one item is required")

    normalized = []
    for index, item in enumerate(items):
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            raise ValueError("each item must be an object")
        product_name = _text(item.get("product_name"))
        if not product_name:
            raise ValueError("product_name is required for each item")
        normalized.append(
            {
                "product_name": product_name,
                "unit": _text(item.get("unit")),
                "quantity": _number(item.get("quantity")),
                "selling_price": _number(item.get("selling_price")),
                "vat_invoice": _bool(item.get("vat_invoice")),
                "notes": _text(item.get("notes")),
                "sort_order": index,
            }
        )
    return normalized


def _to_order_row(payload: dict, clerk_id: str) -> dict:
    customer_id = str(payload.get("customer_id") or "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    _owned_customer(customer_id, clerk_id)
    return {
        "clerk_id": clerk_id,
        "customer_id": customer_id,
        "order_date": _date(payload.get("order_date")),
        "notes": _text(payload.get("notes")),
    }


def _format_order(row: dict) -> dict:
    items = row.pop("order_items", None) or []
    items = sorted(items, key=lambda item: item.get("sort_order") or 0)
    row["items"] = [
        {field: item.get(field) for field in ITEM_FIELDS} for item in items
    ]
    return row


def _owned_query(order_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _replace_items(order_id: str, items: list[dict]) -> None:
    supabase.table(ITEMS_TABLE).delete().eq("order_id", order_id).execute()
    rows = [{**item, "order_id": order_id} for item in items]
    result = supabase.table(ITEMS_TABLE).insert(rows).execute()
    if not result.data:
        raise RuntimeError("Failed to save order items")


def create_order(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    items = _normalize_items(payload.get("items"))
    result = (
        supabase.table(TABLE)
        .insert(_to_order_row(payload, clerk_id))
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create order")
    order_id = result.data[0]["id"]
    try:
        _replace_items(order_id, items)
    except Exception:
        supabase.table(TABLE).delete().eq("id", order_id).eq(
            "clerk_id", clerk_id
        ).execute()
        raise
    return get_order(order_id, clerk_id)


def list_orders(clerk_id: str, customer_id: str | None = None) -> list[dict]:
    query = (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("clerk_id", clerk_id)
        .order("order_date", desc=True)
        .order("created_at", desc=True)
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = query.execute()
    return [_format_order(row) for row in (result.data or [])]


def get_order(order_id: str, clerk_id: str) -> dict:
    result = _owned_query(order_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise OrderNotFoundError("Order not found")
    return _format_order(data[0])


def update_order(order_id: str, clerk_id: str, payload: dict) -> dict:
    get_order(order_id, clerk_id)

    updates = {}
    if "customer_id" in payload and payload["customer_id"] is not None:
        customer_id = str(payload["customer_id"]).strip()
        _owned_customer(customer_id, clerk_id)
        updates["customer_id"] = customer_id
    if "order_date" in payload and payload["order_date"] is not None:
        updates["order_date"] = _date(payload["order_date"])
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = _text(payload["notes"])

    items = None
    if "items" in payload and payload["items"] is not None:
        items = _normalize_items(payload["items"])

    if not updates and items is None:
        return get_order(order_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise OrderNotFoundError("Order not found")
    if items is not None:
        _replace_items(order_id, items)
    return get_order(order_id, clerk_id)


def delete_order(order_id: str, clerk_id: str) -> dict:
    existing = get_order(order_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", order_id).eq("clerk_id", clerk_id).execute()
    return existing
