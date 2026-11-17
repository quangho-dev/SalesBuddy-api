from src.services.clerkAuth import clerk_primary_email
from src.services.supabase import supabase

USERS_TABLE = "users"


def _clean_email(value) -> str:
    return str(value or "").strip().lower()


def ensure_user(clerk_id: str) -> None:
    existing = (
        supabase.table(USERS_TABLE)
        .select("clerk_id")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table(USERS_TABLE).insert({"clerk_id": clerk_id}).execute()


def remember_user_email(clerk_id: str, current_email: str | None = None, email: str | None = None) -> str:
    current = _clean_email(current_email)
    if current_email is None:
        existing = (
            supabase.table(USERS_TABLE)
            .select("email")
            .eq("clerk_id", clerk_id)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        current = _clean_email(rows[0].get("email")) if rows else ""
    if current:
        return current
    resolved = _clean_email(email) or clerk_primary_email(clerk_id)
    if not resolved:
        return ""
    try:
        supabase.table(USERS_TABLE).update({"email": resolved}).eq("clerk_id", clerk_id).execute()
    except Exception as error:
        if "users_email_unique_idx" not in str(error):
            return resolved
    return resolved
