from datetime import datetime, timezone

from src.services.supabase import supabase
from src.services.users import ensure_user

USERS_TABLE = "users"
RAG_SETTINGS_TABLE = "sales_rag_settings"
DEFAULT_PAYMENT_TERM_DAYS = 3
RAG_STRATEGIES = (
    "basic",
    "hybrid",
    "multi-query-vector",
    "multi-query-hybrid",
)


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


def _positive_int(value, name: str, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number") from exc
    if number < 1 or number > maximum:
        raise ValueError(f"{name} must be from 1 to {maximum}")
    return number


def _unit_float(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number < 0 or number > 1:
        raise ValueError(f"{name} must be from 0 to 1")
    return number


def _public_rag_settings(row: dict) -> dict:
    return {
        "rag_strategy": row["rag_strategy"],
        "final_context_size": row["final_context_size"],
        "similarity_threshold": row["similarity_threshold"],
        "chunks_per_search": row["chunks_per_search"],
        "vector_weight": row["vector_weight"],
        "keyword_weight": row["keyword_weight"],
        "number_of_queries": row["number_of_queries"],
    }


def get_rag_settings(clerk_id: str) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(RAG_SETTINGS_TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return _public_rag_settings(result.data[0])
    created = (
        supabase.table(RAG_SETTINGS_TABLE)
        .insert({"clerk_id": clerk_id})
        .execute()
    )
    return _public_rag_settings(created.data[0])


def update_rag_settings(clerk_id: str, payload: dict) -> dict:
    current = get_rag_settings(clerk_id)
    strategy = payload.get("rag_strategy", current["rag_strategy"])
    if strategy not in RAG_STRATEGIES:
        raise ValueError("rag_strategy is not supported")
    saved = {
        "rag_strategy": strategy,
        "final_context_size": _positive_int(
            payload.get("final_context_size", current["final_context_size"]),
            "final_context_size",
            30,
        ),
        "similarity_threshold": _unit_float(
            payload.get("similarity_threshold", current["similarity_threshold"]),
            "similarity_threshold",
        ),
        "chunks_per_search": _positive_int(
            payload.get("chunks_per_search", current["chunks_per_search"]),
            "chunks_per_search",
            30,
        ),
        "vector_weight": _unit_float(
            payload.get("vector_weight", current["vector_weight"]),
            "vector_weight",
        ),
        "keyword_weight": _unit_float(
            payload.get("keyword_weight", current["keyword_weight"]),
            "keyword_weight",
        ),
        "number_of_queries": _positive_int(
            payload.get("number_of_queries", current["number_of_queries"]),
            "number_of_queries",
            6,
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = (
        supabase.table(RAG_SETTINGS_TABLE)
        .update(saved)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to update RAG settings")
    return _public_rag_settings(result.data[0])
