from datetime import date, datetime, timezone

from src.services.orders import OrderNotFoundError, get_order
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "payments"
PAYMENT_METHODS = ("cash", "bank_transfer")
METHOD_ALIASES = {
    "cash": "cash",
    "tien mat": "cash",
    "tiền mặt": "cash",
    "bank_transfer": "bank_transfer",
    "chuyen khoan": "bank_transfer",
    "chuyển khoản": "bank_transfer",
    "transfer": "bank_transfer",
}


class PaymentNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value) -> float:
    if value is None or value == "":
        return 0
    return float(value)


def _date(value) -> str:
    if value is None or value == "":
        return date.today().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _payment_method(value) -> str:
    method = str(value or "").strip().lower()
    normalized = METHOD_ALIASES.get(method)
    if not normalized:
        raise ValueError("payment_method must be cash or bank_transfer")
    return normalized


def _amount(value) -> float:
    amount = _number(value)
    if amount <= 0:
        raise ValueError("amount must be greater than 0")
    return amount


def _owned_order(order_id: str, clerk_id: str) -> dict:
    order_id = str(order_id or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    return get_order(order_id, clerk_id)


def _to_payment_row(payload: dict, clerk_id: str) -> dict:
    order = _owned_order(payload.get("order_id"), clerk_id)
    return {
        "order_id": order["id"],
        "amount": _amount(payload.get("amount")),
        "payment_date": _date(payload.get("payment_date")),
        "payment_method": _payment_method(payload.get("payment_method")),
    }


def _owned_query(payment_id: str):
    return supabase.table(TABLE).select("*").eq("id", payment_id).limit(1)


def _user_order_ids(clerk_id: str) -> list[str]:
    result = (
        supabase.table("orders")
        .select("id")
        .eq("clerk_id", clerk_id)
        .execute()
    )
    return [row["id"] for row in (result.data or [])]


def create_payment(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(TABLE)
        .insert(_to_payment_row(payload, clerk_id))
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create payment")
    return result.data[0]


def list_payments(clerk_id: str, order_id: str | None = None) -> list[dict]:
    query = supabase.table(TABLE).select("*")
    if order_id:
        _owned_order(order_id, clerk_id)
        query = query.eq("order_id", order_id)
    else:
        order_ids = _user_order_ids(clerk_id)
        if not order_ids:
            return []
        query = query.in_("order_id", order_ids)
    result = (
        query.order("payment_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_payment(payment_id: str, clerk_id: str) -> dict:
    result = _owned_query(payment_id).execute()
    data = result.data or []
    if not data:
        raise PaymentNotFoundError("Payment not found")
    payment = data[0]
    try:
        _owned_order(payment["order_id"], clerk_id)
    except OrderNotFoundError:
        raise PaymentNotFoundError("Payment not found")
    return payment


def update_payment(payment_id: str, clerk_id: str, payload: dict) -> dict:
    existing = get_payment(payment_id, clerk_id)

    updates = {}
    if "order_id" in payload and payload["order_id"] is not None:
        order = _owned_order(payload["order_id"], clerk_id)
        updates["order_id"] = order["id"]
    if "amount" in payload and payload["amount"] is not None:
        updates["amount"] = _amount(payload["amount"])
    if "payment_date" in payload and payload["payment_date"] is not None:
        updates["payment_date"] = _date(payload["payment_date"])
    if "payment_method" in payload and payload["payment_method"] is not None:
        updates["payment_method"] = _payment_method(payload["payment_method"])

    if not updates:
        return existing

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", payment_id)
        .execute()
    )
    if not result.data:
        raise PaymentNotFoundError("Payment not found")
    return get_payment(payment_id, clerk_id)


def delete_payment(payment_id: str, clerk_id: str) -> dict:
    existing = get_payment(payment_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", payment_id).execute()
    return existing
