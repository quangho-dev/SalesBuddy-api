from datetime import datetime, timezone

from src.services.customers import get_customer
from src.services.orders import create_order, find_order_for_quote, get_order
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "quotes"
ITEMS_TABLE = "quote_items"
EVENTS_TABLE = "quote_status_events"
CUSTOMER_EMBED = "id, company_name, contact_person, phone_number, address, tax_code, payment_term_days"
EVENT_FIELDS = "id, previous_quote_status, quote_status, reason, order_id, created_at"
SELECT_FIELDS = (
    f"*, customers({CUSTOMER_EMBED}), quote_items(*), orders(id), "
    f"quote_status_events({EVENT_FIELDS})"
)
ITEM_FIELDS = (
    "id",
    "product_name",
    "unit",
    "quantity",
    "selling_price",
    "vat_invoice",
    "notes",
)
VAT_RATE = 0.1


class QuoteNotFoundError(LookupError):
    pass


QUOTE_STATUSES = {"converted", "failed", "unset"}


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


def _line_total(item: dict) -> float:
    return _number(item.get("quantity")) * _number(item.get("selling_price"))


def _line_vat(item: dict) -> float:
    if not _bool(item.get("vat_invoice")):
        return 0
    return round(_line_total(item) * VAT_RATE)


def _totals(items: list[dict]) -> dict:
    subtotal = sum(_line_total(item) for item in items)
    vat_total = sum(_line_vat(item) for item in items)
    return {
        "subtotal": subtotal,
        "vat_total": vat_total,
        "grand_total": subtotal + vat_total,
    }


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


def _linked_order_id(row: dict) -> str | None:
    orders = row.pop("orders", None) or []
    if isinstance(orders, dict):
        orders = [orders]
    for order in orders:
        order_id = str((order or {}).get("id") or "").strip()
        if order_id:
            return order_id
    return None


def _format_quote(row: dict) -> dict:
    items = row.pop("quote_items", None) or []
    items = sorted(items, key=lambda item: item.get("sort_order") or 0)
    row["items"] = [
        {field: item.get(field) for field in ITEM_FIELDS} for item in items
    ]
    row["order_id"] = _linked_order_id(row)
    events = row.pop("quote_status_events", None) or []
    row["status_events"] = sorted(
        events,
        key=lambda event: event.get("created_at") or "",
        reverse=True,
    )
    return row


def _stored_status(quote: dict) -> str:
    status = _text(quote.get("status"))
    if status in QUOTE_STATUSES:
        return status
    return "unset"


def _record_status_event(
    clerk_id: str,
    quote: dict,
    status: str,
    reason: str,
) -> None:
    order_id = _text(quote.get("order_id")) or None
    supabase.table(EVENTS_TABLE).insert(
        {
            "clerk_id": clerk_id,
            "quote_id": quote.get("id"),
            "order_id": order_id,
            "previous_quote_status": _stored_status(quote),
            "quote_status": status,
            "previous_order_status": "",
            "order_status": "",
            "reason": reason[:1000],
        }
    ).execute()


def _owned_query(quote_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("id", quote_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _replace_items(quote_id: str, items: list[dict]) -> None:
    supabase.table(ITEMS_TABLE).delete().eq("quote_id", quote_id).execute()
    rows = [{**item, "quote_id": quote_id} for item in items]
    result = supabase.table(ITEMS_TABLE).insert(rows).execute()
    if not result.data:
        raise RuntimeError("Failed to save quote items")


def _owned_customer(customer_id: str, clerk_id: str) -> dict:
    return get_customer(customer_id, clerk_id)


def create_quote(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    customer_id = str(payload.get("customer_id") or "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    _owned_customer(customer_id, clerk_id)
    items = _normalize_items(payload.get("items"))
    result = (
        supabase.table(TABLE)
        .insert(
            {
                "clerk_id": clerk_id,
                "customer_id": customer_id,
                "notes": _text(payload.get("notes")),
                **_totals(items),
            }
        )
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create quote")
    quote_id = result.data[0]["id"]
    try:
        _replace_items(quote_id, items)
    except Exception:
        supabase.table(TABLE).delete().eq("id", quote_id).eq(
            "clerk_id", clerk_id
        ).execute()
        raise
    return get_quote(quote_id, clerk_id)


def list_quotes(clerk_id: str, customer_id: str | None = None) -> list[dict]:
    query = (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = query.execute()
    return [_format_quote(row) for row in (result.data or [])]


def get_quote(quote_id: str, clerk_id: str) -> dict:
    result = _owned_query(quote_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise QuoteNotFoundError("Quote not found")
    return _format_quote(data[0])


def update_quote(quote_id: str, clerk_id: str, payload: dict) -> dict:
    get_quote(quote_id, clerk_id)

    updates = {}
    if "customer_id" in payload and payload["customer_id"] is not None:
        customer_id = str(payload["customer_id"]).strip()
        _owned_customer(customer_id, clerk_id)
        updates["customer_id"] = customer_id
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = _text(payload["notes"])

    items = None
    if "items" in payload and payload["items"] is not None:
        items = _normalize_items(payload["items"])
        updates.update(_totals(items))

    if not updates and items is None:
        return get_quote(quote_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", quote_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise QuoteNotFoundError("Quote not found")
    if items is not None:
        _replace_items(quote_id, items)
    return get_quote(quote_id, clerk_id)


def save_quote_drive_file(
    quote_id: str,
    clerk_id: str,
    file_id: str,
    file_name: str,
    web_link: str,
) -> dict:
    get_quote(quote_id, clerk_id)
    result = (
        supabase.table(TABLE)
        .update(
            {
                "drive_file_id": _text(file_id),
                "drive_file_name": _text(file_name),
                "drive_web_link": _text(web_link),
                "updated_at": _now(),
            }
        )
        .eq("id", quote_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise QuoteNotFoundError("Quote not found")
    return get_quote(quote_id, clerk_id)


def set_quote_status(
    quote_id: str, clerk_id: str, status: str, reason: str = ""
) -> dict:
    if status not in QUOTE_STATUSES:
        raise ValueError("Trạng thái báo giá không hợp lệ.")
    quote = get_quote(quote_id, clerk_id)
    previous = _stored_status(quote)
    reason_text = _text(reason)[:1000] if status == "failed" else ""
    previous_reason = (
        _text(quote.get("conversion_error"))[:1000] if previous == "failed" else ""
    )
    updates = {
        "status": status,
        "converted_to_order": status == "converted",
        "conversion_error": reason_text,
        "updated_at": _now(),
    }
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", quote_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise QuoteNotFoundError("Quote not found")
    if previous != status or previous_reason != reason_text:
        _record_status_event(clerk_id, quote, status, reason_text)
    return get_quote(quote_id, clerk_id)


def convert_quote_to_order(quote_id: str, clerk_id: str) -> dict:
    quote = get_quote(quote_id, clerk_id)
    existing = find_order_for_quote(quote_id, clerk_id)
    if existing and existing.get("id"):
        set_quote_status(quote_id, clerk_id, "converted")
        return get_order(str(existing["id"]), clerk_id)
    try:
        order = create_order(
            clerk_id,
            {
                "customer_id": quote.get("customer_id"),
                "notes": quote.get("notes") or "",
                "items": quote.get("items") or [],
                "is_paid": False,
                "quote_id": quote_id,
            },
        )
    except QuoteNotFoundError:
        raise
    except Exception as exc:
        set_quote_status(quote_id, clerk_id, "failed", str(exc))
        raise
    set_quote_status(quote_id, clerk_id, "converted")
    return order


def delete_quote(quote_id: str, clerk_id: str) -> dict:
    existing = get_quote(quote_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", quote_id).eq("clerk_id", clerk_id).execute()
    return existing
