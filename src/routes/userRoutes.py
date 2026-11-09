from fastapi import APIRouter, HTTPException
from src.services.users import UserEmailRequiredError, email_from_clerk_payload, link_user

router = APIRouter(tags=["userRoutes"])


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

        email = email_from_clerk_payload(user_data)
        if not email:
            raise HTTPException(
                status_code=400, detail="Missing email address in user data"
            )

        try:
            user = link_user(clerk_id, email)
        except UserEmailRequiredError as error:
            raise HTTPException(status_code=400, detail=str(error))
        return {"message": "User linked successfully", "user": user}

    except HTTPException as e:
        raise e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error occurred while processing webhook {str(e)}",
        )
