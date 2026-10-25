from src.services.supabase import supabase
from src.services.users import ensure_user

USERS_TABLE = "users"
DEFAULT_PAYMENT_TERM_DAYS = 3


def _nonneg_int(value, default: int = DEFAULT_PAYMENT_TERM_DAYS) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(round(float(str(value).strip().replace(",", "."))))
    except (TypeError, ValueError) as exc:
        raise ValueError("default_payment_term_days must be a number") from exc
    if number < 0:
        raise ValueError("default_payment_term_days must be >= 0")
    return number


def get_settings(clerk_id: str) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(USERS_TABLE)
        .select("default_payment_term_days")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    days = rows[0].get("default_payment_term_days") if rows else None
    return {"default_payment_term_days": _nonneg_int(days)}


def update_settings(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    days = _nonneg_int(payload.get("default_payment_term_days"))
    result = (
        supabase.table(USERS_TABLE)
        .update({"default_payment_term_days": days})
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to update settings")
    return {"default_payment_term_days": days}
