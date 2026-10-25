from datetime import date, datetime, timezone

from src.services.customers import CustomerNotFoundError, get_customer
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "orders"
ITEMS_TABLE = "order_items"
VAT_RATE = 0.1
CUSTOMER_EMBED = "id, company_name, contact_person, phone_number, address, tax_code, payment_term_days"
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


PAYMENT_METHODS = {
    "cash": "cash",
    "tien mat": "cash",
    "tiền mặt": "cash",
    "bank_transfer": "bank_transfer",
    "chuyen khoan": "bank_transfer",
    "chuyển khoản": "bank_transfer",
    "transfer": "bank_transfer",
}


def _payment_method(value):
    if value is None or str(value).strip() == "":
        return None
    method = PAYMENT_METHODS.get(str(value).strip().lower())
    if not method:
        raise ValueError("payment_method must be cash or bank_transfer")
    return method


def _paid_amount(value) -> float:
    amount = _number(value)
    if amount < 0:
        raise ValueError("paid_amount must be >= 0")
    return amount


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
    row = {
        "clerk_id": clerk_id,
        "customer_id": customer_id,
        "order_date": _date(payload.get("order_date")),
        "notes": _text(payload.get("notes")),
        "is_paid": _bool(payload.get("is_paid")),
        "payment_method": _payment_method(payload.get("payment_method")),
        "paid_amount": _paid_amount(payload.get("paid_amount")),
    }
    quote_id = str(payload.get("quote_id") or "").strip()
    if quote_id:
        row["quote_id"] = quote_id
    return row


def _format_order(row: dict) -> dict:
    items = row.pop("order_items", None) or []
    items = sorted(items, key=lambda item: item.get("sort_order") or 0)
    row["items"] = [
        {field: item.get(field) for field in ITEM_FIELDS} for item in items
    ]
    row["is_paid"] = _bool(row.get("is_paid"))
    row["payment_method"] = _payment_method(row.get("payment_method"))
    row["paid_amount"] = _paid_amount(row.get("paid_amount"))
    return row


def _owned_query(order_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _items_grand(items: list[dict]) -> float:
    total = 0.0
    for item in items:
        line = float(item.get("quantity") or 0) * float(item.get("selling_price") or 0)
        if item.get("vat_invoice"):
            line += round(line * VAT_RATE)
        total += line
    return total


def _payment_to_record(payload: dict, items: list[dict]) -> dict | None:
    if not _bool(payload.get("is_paid")):
        return None
    method = _payment_method(payload.get("payment_method"))
    if not method:
        raise ValueError("Hãy chọn hình thức thanh toán trước khi đánh dấu đã thanh toán.")
    amount = _paid_amount(payload.get("paid_amount"))
    if amount <= 0:
        amount = _items_grand(items)
    if amount <= 0:
        raise ValueError("Tổng số tiền thanh toán phải lớn hơn 0.")
    return {"payment_method": method, "amount": amount}


def _insert_payment(clerk_id: str, order_id: str, payment: dict) -> None:
    from src.services.payments import create_payment

    create_payment(
        clerk_id,
        {
            "order_id": order_id,
            "amount": payment["amount"],
            "payment_method": payment["payment_method"],
        },
    )


def _delete_order_payments(order_id: str) -> None:
    supabase.table("payments").delete().eq("order_id", order_id).execute()


def _replace_items(order_id: str, items: list[dict]) -> None:
    supabase.table(ITEMS_TABLE).delete().eq("order_id", order_id).execute()
    rows = [{**item, "order_id": order_id} for item in items]
    result = supabase.table(ITEMS_TABLE).insert(rows).execute()
    if not result.data:
        raise RuntimeError("Failed to save order items")


def create_order(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    items = _normalize_items(payload.get("items"))
    payment = _payment_to_record(payload, items)
    if payment:
        payload = {
            **payload,
            "payment_method": payment["payment_method"],
            "paid_amount": payment["amount"],
        }
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
        if payment:
            _insert_payment(clerk_id, order_id, payment)
    except Exception:
        supabase.table("payments").delete().eq("order_id", order_id).execute()
        supabase.table(TABLE).delete().eq("id", order_id).eq(
            "clerk_id", clerk_id
        ).execute()
        raise
    return get_order(order_id, clerk_id)


def list_orders(
    clerk_id: str,
    customer_id: str | None = None,
    is_paid: bool | None = None,
) -> list[dict]:
    query = (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("clerk_id", clerk_id)
        .order("order_date", desc=True)
        .order("created_at", desc=True)
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    if is_paid is not None:
        query = query.eq("is_paid", is_paid)
    result = query.execute()
    return [_format_order(row) for row in (result.data or [])]


def get_order(order_id: str, clerk_id: str) -> dict:
    result = _owned_query(order_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise OrderNotFoundError("Order not found")
    return _format_order(data[0])


def update_order(order_id: str, clerk_id: str, payload: dict) -> dict:
    existing = get_order(order_id, clerk_id)
    was_paid = bool(existing.get("is_paid"))

    updates = {}
    if "customer_id" in payload and payload["customer_id"] is not None:
        customer_id = str(payload["customer_id"]).strip()
        _owned_customer(customer_id, clerk_id)
        updates["customer_id"] = customer_id
    if "order_date" in payload and payload["order_date"] is not None:
        updates["order_date"] = _date(payload["order_date"])
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = _text(payload["notes"])
    if "is_paid" in payload and payload["is_paid"] is not None:
        updates["is_paid"] = _bool(payload["is_paid"])
    if "payment_method" in payload:
        updates["payment_method"] = _payment_method(payload.get("payment_method"))
    if "paid_amount" in payload and payload["paid_amount"] is not None:
        updates["paid_amount"] = _paid_amount(payload["paid_amount"])

    items = None
    if "items" in payload and payload["items"] is not None:
        items = _normalize_items(payload["items"])

    payment = None
    clear_payments = was_paid and "is_paid" in updates and not updates["is_paid"]
    if not was_paid:
        payment_items = items if items is not None else existing.get("items") or []
        payment_payload = {
            "is_paid": updates["is_paid"] if "is_paid" in updates else existing.get("is_paid"),
            "payment_method": (
                updates["payment_method"]
                if "payment_method" in updates
                else existing.get("payment_method")
            ),
            "paid_amount": (
                updates["paid_amount"]
                if "paid_amount" in updates
                else existing.get("paid_amount")
            ),
        }
        if "payment_method" in payload or "paid_amount" in payload:
            payment = _payment_to_record(payment_payload, payment_items)
            if payment and "is_paid" in payload:
                updates["payment_method"] = payment["payment_method"]
                updates["paid_amount"] = payment["amount"]

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
    if payment:
        try:
            _insert_payment(clerk_id, order_id, payment)
        except Exception:
            supabase.table(TABLE).update(
                {"is_paid": was_paid, "updated_at": _now()}
            ).eq("id", order_id).eq("clerk_id", clerk_id).execute()
            raise
    if clear_payments:
        _delete_order_payments(order_id)
    return get_order(order_id, clerk_id)


def save_order_drive_file(
    order_id: str,
    clerk_id: str,
    file_id: str,
    file_name: str,
    web_link: str,
) -> dict:
    get_order(order_id, clerk_id)
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
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise OrderNotFoundError("Order not found")
    return get_order(order_id, clerk_id)


def delete_order(order_id: str, clerk_id: str) -> dict:
    existing = get_order(order_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", order_id).eq("clerk_id", clerk_id).execute()
    return existing
