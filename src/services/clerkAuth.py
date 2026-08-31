from src.config.index import appConfig
from fastapi import Request, HTTPException, Depends

from clerk_backend_api import Clerk
from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions

ADMIN_ROLE = "admin"

def _get_clerk_sdk() -> Clerk:
    return Clerk(appConfig["clerk_secret_key"])


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
