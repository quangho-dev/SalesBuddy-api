from src.agents.search_target_customers_agents.supervisor_agent import create_supervisor_agent
from src.config.index import appConfig
from src.services.clerkAuth import get_current_user_clerk_id
from src.services.searchSessions import (
    SearchSessionCustomerNotFoundError,
    SearchSessionNotFoundError,
    create_search_session,
    delete_search_session,
    get_search_session,
    remove_customer_from_session,
)
from src.services.targetCustomers import (
    create_target_customer_list,
    get_owned_target_customer_list,
    list_target_customer_lists,
    save_search_results,
)
from fastapi import APIRouter, Depends, HTTPException
from langsmith import tracing_context
from pydantic import BaseModel, Field
from uuid import UUID

router = APIRouter(tags=["searchTargetCustomersRoutes"])


class SearchTargetCustomersRequest(BaseModel):
    query: str
    target_customer_list_id: UUID


class CreateTargetCustomerListRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


def _structured_payload(structured) -> dict:
    if hasattr(structured, "model_dump"):
        return structured.model_dump()
    if isinstance(structured, dict):
        return structured
    return {}


@router.get("/lists")
async def get_target_customer_lists(
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return list_target_customer_lists(user_clerk_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load target customer lists: {str(e)}",
        )


@router.post("/lists")
async def create_list(
    body: CreateTargetCustomerListRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        return create_target_customer_list(
            user_clerk_id,
            body.name,
            body.description,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create target customer list: {str(e)}",
        )


@router.post("/search-target-customers")
async def search_target_customers(
    body: SearchTargetCustomersRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    list_id = str(body.target_customer_list_id)
    if not get_owned_target_customer_list(list_id, user_clerk_id):
        raise HTTPException(
            status_code=404,
            detail="Target customer list not found",
        )

    supervisor_agent = create_supervisor_agent(clerk_id=user_clerk_id)
    invoke_config = {
        "run_name": "search_target_customers",
        "tags": ["search-target-customers"],
        "metadata": {
            "query": body.query,
            "clerk_id": user_clerk_id,
            "target_customer_list_id": list_id,
        },
    }

    with tracing_context(
        enabled=appConfig["langsmith_enabled"],
        project_name=appConfig["langsmith_project"],
        tags=["search-target-customers"],
        metadata={
            "query": body.query,
            "clerk_id": user_clerk_id,
            "target_customer_list_id": list_id,
        },
    ):
        result = supervisor_agent.invoke(
            {"messages": [{"role": "user", "content": body.query}]},
            config=invoke_config,
        )

    payload = _structured_payload(result.get("structured_response"))
    customers = payload.get("final_target_customer_info") or []

    try:
        session = create_search_session(
            clerk_id=user_clerk_id,
            list_id=list_id,
            query=body.query,
            customers=customers,
        )
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="Target customer list not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create search session: {str(e)}",
        )

    return {
        "search_id": session["search_id"],
        "list": session["list"],
        "customers": session["customers"],
        "saved": False,
    }


@router.delete("/search-sessions/{search_id}/customers/{customer_id}")
async def delete_found_target_customer(
    search_id: UUID,
    customer_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        session = remove_customer_from_session(
            str(search_id), user_clerk_id, str(customer_id)
        )
    except SearchSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Search session not found")
    except SearchSessionCustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Target customer not found")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove target customer: {str(e)}",
        )

    return {
        "search_id": session["search_id"],
        "list": session["list"],
        "customers": session["customers"],
        "saved": False,
    }


@router.post("/search-sessions/{search_id}/confirm")
async def confirm_target_customers(
    search_id: UUID,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    try:
        session = get_search_session(str(search_id), user_clerk_id)
        saved = save_search_results(
            clerk_id=user_clerk_id,
            customers=session["customers"],
            list_id=session["list"]["id"],
        )
        delete_search_session(str(search_id))
    except SearchSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Search session not found")
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="Target customer list not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save target customers: {str(e)}",
        )

    return {
        "search_id": str(search_id),
        "list": saved["list"],
        "customers": saved["customers"],
        "saved": True,
    }
