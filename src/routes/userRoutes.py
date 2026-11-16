from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.organizations import (
    OrganizationInputError,
    get_current_user,
    join_organization,
)
from src.services.supabase import supabase

router = APIRouter(tags=["userRoutes"])


class JoinOrganizationRequest(BaseModel):
    name: str = ""
    tax_code: str = ""


@router.get("/me")
async def read_current_user(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return get_current_user(user_clerk_id)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load user: {str(error)}",
        )


@router.post("/organization")
async def assign_organization(
    body: JoinOrganizationRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return join_organization(user_clerk_id, body.name, body.tax_code)
    except OrganizationInputError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to assign organization: {str(error)}",
        )


@router.post("/create")
async def create_user(clerk_webhook_data: dict):
    """
    Payload structure : https://clerk.com/docs/guides/development/webhooks/overview#payload-structure

    Logic Flow
    * 1. Validate webhook payload structure
    * 2. Check event type - our case type - "user.created"
    * 3. Extract and validate user data
    * 4. Extract and validate clerk_id
    * 5. Check if user already exists to prevent duplicates
    * 6. Create new user in database
    * 7. Return success message and user data

    """
    try:
        # Validate webhook payload structure
        if not isinstance(clerk_webhook_data, dict):
            raise HTTPException(
                status_code=400, detail="Invalid webhook payload format"
            )

        # Check event type
        event_type = clerk_webhook_data.get("type")
        if event_type != "user.created":
            return {"message": f"Event type '{event_type}' ignored"}

        # Extract and validate user data
        user_data = clerk_webhook_data.get("data")
        if not user_data or not isinstance(user_data, dict):
            raise HTTPException(
                status_code=400,
                detail="Missing or invalid user data in webhook payload",
            )

        # Extract and validate clerk_id
        clerk_id = user_data.get("id")
        if not clerk_id or not isinstance(clerk_id, str):
            raise HTTPException(
                status_code=400, detail="Missing or invalid clerk_id in user data"
            )

        # Check if user already exists to prevent duplicates
        existing_user = (
            supabase.table("users")
            .select("clerk_id")
            .eq("clerk_id", clerk_id)
            .execute()
        )
        if existing_user.data:
            return {"message": "User already exists", "clerk_id": clerk_id}

        # Create new user in database
        result = supabase.table("users").insert({"clerk_id": clerk_id}).execute()
        if not result.data:
            raise HTTPException(
                status_code=500, detail="Failed to create user in database"
            )

        return {"message": "User created successfully", "user": result.data[0]}

    except HTTPException as e:
        raise e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error occurred while processing webhook {str(e)}",
        )
