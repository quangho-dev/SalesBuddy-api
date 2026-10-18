from src.services.supabase import supabase

USERS_TABLE = "users"


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
