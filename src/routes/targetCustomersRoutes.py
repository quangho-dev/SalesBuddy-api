from src.agents.search_target_customers_agents.supervisor_agent import create_supervisor_agent
from src.config.index import appConfig
from src.services.clerkAuth import get_current_user_clerk_id
from fastapi import APIRouter, Depends, HTTPException
from langsmith import tracing_context
from pydantic import BaseModel
from src.services.supabase import supabase

router = APIRouter(tags=["searchTargetCustomersRoutes"])


class SearchTargetCustomersRequest(BaseModel):
    query: str


@router.post("/search-target-customers")
async def search_target_customers(
    body: SearchTargetCustomersRequest,
    # _user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    supervisor_agent = create_supervisor_agent()
    invoke_config = {
        "run_name": "search_target_customers",
        "tags": ["search-target-customers"],
        "metadata": {"query": body.query},
    }

    with tracing_context(
        enabled=appConfig["langsmith_enabled"],
        project_name=appConfig["langsmith_project"],
        tags=["search-target-customers"],
        metadata={"query": body.query},
    ):
        result = supervisor_agent.invoke(
            {"messages": [{"role": "user", "content": body.query}]},
            config=invoke_config,
        )

    structured = result.get("structured_response")
    if hasattr(structured, "model_dump"):
        return structured.model_dump()["final_target_customer_info"]
    if isinstance(structured, dict):
        return structured.get("final_target_customer_info", [])
    return []
