from src.services.supabase import supabase

USERS_TABLE = "users"


class UserEmailRequiredError(ValueError):
    pass


def _normalize_email(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _rows(result) -> list[dict]:
    return result.data or []


def _find_by_clerk_id(clerk_id: str) -> dict | None:
    result = (
        supabase.table(USERS_TABLE)
        .select("id, clerk_id, email")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _find_by_email(email: str) -> dict | None:
    result = (
        supabase.table(USERS_TABLE)
        .select("id, clerk_id, email")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _email_from_clerk_user(user) -> str:
    primary_id = getattr(user, "primary_email_address_id", None)
    addresses = getattr(user, "email_addresses", None) or []
    fallback = ""
    for item in addresses:
        if isinstance(item, dict):
            address = item.get("email_address")
            item_id = item.get("id")
        else:
            address = getattr(item, "email_address", None)
            item_id = getattr(item, "id", None)
        normalized = _normalize_email(address)
        if not normalized:
            continue
        if primary_id and item_id == primary_id:
            return normalized
        if not fallback:
            fallback = normalized
    return fallback


def _email_from_clerk(clerk_id: str) -> str:
    from src.services.clerkAuth import _get_clerk_sdk

    try:
        user = _get_clerk_sdk().users.get(user_id=clerk_id)
    except Exception as error:
        raise UserEmailRequiredError(
            "Không lấy được email người dùng từ Clerk."
        ) from error
    email = _email_from_clerk_user(user)
    if not email:
        raise UserEmailRequiredError("Không lấy được email người dùng từ Clerk.")
    return email


def email_from_clerk_payload(data: dict) -> str:
    primary_id = data.get("primary_email_address_id")
    fallback = ""
    for item in data.get("email_addresses") or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_email(item.get("email_address"))
        if not normalized:
            continue
        if primary_id and item.get("id") == primary_id:
            return normalized
        if not fallback:
            fallback = normalized
    return fallback


def link_user(clerk_id: str, email: str) -> dict:
    """Match the person by email, then store the Clerk id used to sign in."""
    clerk_id = str(clerk_id or "").strip()
    email = _normalize_email(email)
    if not clerk_id:
        raise ValueError("clerk_id is required")
    if not email:
        raise UserEmailRequiredError("Không lấy được email người dùng từ Clerk.")

    matched = _find_by_email(email)
    if matched:
        if matched.get("clerk_id") == clerk_id and _normalize_email(matched.get("email")) == email:
            return matched
        result = (
            supabase.table(USERS_TABLE)
            .update({"clerk_id": clerk_id, "email": email})
            .eq("id", matched["id"])
            .execute()
        )
        rows = _rows(result)
        if not rows:
            raise RuntimeError("Failed to link user")
        return rows[0]

    current = _find_by_clerk_id(clerk_id)
    if current:
        if _normalize_email(current.get("email")) == email:
            return current
        result = (
            supabase.table(USERS_TABLE)
            .update({"email": email})
            .eq("id", current["id"])
            .execute()
        )
        rows = _rows(result)
        if not rows:
            raise RuntimeError("Failed to save user email")
        return rows[0]

    result = (
        supabase.table(USERS_TABLE)
        .insert({"clerk_id": clerk_id, "email": email})
        .execute()
    )
    rows = _rows(result)
    if not rows:
        raise RuntimeError("Failed to create user")
    return rows[0]


def ensure_user(clerk_id: str) -> None:
    clerk_id = str(clerk_id or "").strip()
    if not clerk_id:
        raise ValueError("clerk_id is required")
    current = _find_by_clerk_id(clerk_id)
    if current and _normalize_email(current.get("email")):
        return
    link_user(clerk_id, _email_from_clerk(clerk_id))
