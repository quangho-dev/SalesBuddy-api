from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langchain.messages import HumanMessage
from src.services.clerkAuth import get_current_user_clerk_id

import sys
import os

from dotenv import load_dotenv
load_dotenv()

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)

from scripts import base_tools, prompts, utils


checkpointer = InMemorySaver()
model = ChatOpenAI(
    model="gpt-6-astra",
    use_responses_api=True,
    reasoning_effort="medium",
)

router = APIRouter(tags=["chatRoutes"])

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=2)
    thread_id: str = "default"

async def get_tools():
    mcp_config = utils.load_mcp_config("google-sheets")

    client = MultiServerMCPClient(mcp_config)

    mcp_tools = await client.get_tools()

    tools = mcp_tools

    # Filter tools that work with Gemini
    problematic_tools = ['update_cells']
    
    safe_tools = [tool for tool in tools if tool.name not in problematic_tools]

    print(f"Loaded {len(tools)} Tools")
    print(f"Tools Available\n{[tool.name for tool in tools]}")

    return safe_tools

async def google_sheet_agent(query, thread_id="default"):
    tools = await get_tools()

    agent = create_agent(model=model,
                         tools=tools, 
                         system_prompt=prompts.GOOGLE_SHEETS_PROMPT,
                         checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}}
    result = await agent.ainvoke({'messages': [HumanMessage(query)]}, config=config)

    return _message_text(result["messages"][-1])


def _message_text(message) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        return "\n".join(parts).strip()
    return str(content or "").strip()


@router.post("")
@router.post("/")
async def chat(
    request: ChatRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt!")

    try:
        thread_id = request.thread_id.strip() or user_clerk_id
        response = await google_sheet_agent(request.prompt, thread_id=thread_id)

        return {"response": response}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {e}")