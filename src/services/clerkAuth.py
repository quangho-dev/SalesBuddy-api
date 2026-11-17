from src.config.index import appConfig
from fastapi import Request, HTTPException, Depends

from clerk_backend_api import Clerk
from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions

ADMIN_ROLE = "admin"

def _get_clerk_sdk() -> Clerk:
    return Clerk(appConfig["clerk_secret_key"])


def _primary_email(user) -> str:
    emails = getattr(user, "email_addresses", None) or []
    primary_id = getattr(user, "primary_email_address_id", None)
    fallback = ""
    for item in emails:
        address = str(getattr(item, "email_address", "") or "").strip().lower()
        if not address:
            continue
        if primary_id and getattr(item, "id", None) == primary_id:
            return address
        if not fallback:
            fallback = address
    return fallback


def _display_name(user) -> str:
    parts = [
        str(getattr(user, "first_name", "") or "").strip(),
        str(getattr(user, "last_name", "") or "").strip(),
    ]
    full = " ".join(part for part in parts if part)
    if full:
        return full
    return str(getattr(user, "username", "") or "").strip()


def clerk_primary_email(clerk_id: str) -> str:
    try:
        user = _get_clerk_sdk().users.get(user_id=clerk_id)
    except Exception:
        return ""
    return _primary_email(user)


def clerk_profiles(clerk_ids: list[str]) -> dict[str, dict[str, str]]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw in clerk_ids:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            ids.append(value)
    profiles = {item: {"email": "", "name": ""} for item in ids}
    if not ids:
        return profiles
    try:
        sdk = _get_clerk_sdk()
    except Exception:
        return profiles
    for start in range(0, len(ids), 100):
        chunk = ids[start : start + 100]
        try:
            users = sdk.users.list(request={"user_id": chunk, "limit": 100})
        except Exception:
            continue
        for user in users or []:
            user_id = str(getattr(user, "id", "") or "")
            if user_id not in profiles:
                continue
            profiles[user_id] = {"email": _primary_email(user), "name": _display_name(user)}
    return profiles


def get_current_user_clerk_id(request: Request) -> str:
    try:
        sdk = _get_clerk_sdk()
        
        request_state = sdk.authenticate_request(
            request,
            options=AuthenticateRequestOptions(authorized_parties=[appConfig["domain"]]),
        )

        if not request_state.is_signed_in:
            reason = getattr(request_state, "reason", None) or "unknown"
            raise HTTPException(
                status_code=401,
                detail=f"User is not signed in ({reason})",
            )

        clerk_id = request_state.payload.get("sub")

        if not clerk_id:
            raise HTTPException(status_code=401, detail="Clerk ID not found in token")

        return clerk_id

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Clerk SDK Failed. {str(e)}",
        )


def require_admin_user(
    clerk_id: str = Depends(get_current_user_clerk_id),
) -> str:
    try:
        sdk = _get_clerk_sdk()
        user = sdk.users.get(user_id=clerk_id)
        role = (user.public_metadata or {}).get("role")

        if role != ADMIN_ROLE:
            raise HTTPException(
                status_code=403,
                detail="Admin access required",
            )

        return clerk_id

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify admin role. {str(e)}",
        )
