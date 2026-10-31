import os
from collections.abc import AsyncIterator

from langchain.agents import create_agent
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from src.scripts.prompts import (
    GOOGLE_SHEETS_PROMPT,
    chat_supervisor_prompt,
    sales_database_prompt,
)
from src.scripts.utils import load_mcp_config

checkpointer = InMemorySaver()
model = ChatOpenAI(
    model="gpt-6-astra",
    use_responses_api=True,
    reasoning_effort="medium",
)


def _error_text(exc: BaseException) -> str:
    exceptions = getattr(exc, "exceptions", None)
    if exceptions:
        return "; ".join(_error_text(item) for item in exceptions)
    return str(exc)


def _repair_dangling_tool_calls(messages) -> list[ToolMessage]:
    """Add outputs for tool calls that were saved before the tool failed.

    The Responses API rejects the next turn when a function call has no output.
    """
    answered = {
        message.tool_call_id
        for message in messages
        if isinstance(message, ToolMessage) and message.tool_call_id
    }
    repairs = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls or []:
            call_id = call.get("id")
            if not call_id or call_id in answered:
                continue
            repairs.append(
                ToolMessage(
                    content="Tool failed before it could return a result.",
                    tool_call_id=call_id,
                    status="error",
                )
            )
            answered.add(call_id)
    return repairs


_TOOL_STATUS = {
    "query_supabase": "Đang tra cứu database...",
    "query_google_sheets": "Đang tra cứu Google Sheets...",
}


def _is_supervisor_turn(metadata: dict | None) -> bool:
    tags = (metadata or {}).get("tags") or []
    if "supabase" in tags or "google-sheets" in tags:
        return False
    if "supervisor" in tags:
        return True
    return (metadata or {}).get("langgraph_node") == "model"


def _chunk_text(message) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
            text = block.get("text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _tool_names(message) -> list[str]:
    names = []
    for call in getattr(message, "tool_call_chunks", None) or []:
        name = call.get("name") if isinstance(call, dict) else None
        if name:
            names.append(name)
    for call in getattr(message, "tool_calls", None) or []:
        name = call.get("name") if isinstance(call, dict) else None
        if name:
            names.append(name)
    return names


def _messages_from_update(update) -> list:
    if isinstance(update, dict):
        messages = update.get("messages") or []
    else:
        messages = update or []
    if isinstance(messages, (AIMessage, ToolMessage, HumanMessage)):
        return [messages]
    if isinstance(messages, list):
        return messages
    return []


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


def _supabase_mcp_config() -> dict:
    config = load_mcp_config("supabase")
    server = config.get("supabase")
    if not server:
        raise RuntimeError("Supabase MCP is not configured.")
    token = (os.getenv("SUPABASE_ACCESS_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "SUPABASE_ACCESS_TOKEN is not set. The database assistant cannot sign in to Supabase."
        )
    server["headers"] = {"Authorization": f"Bearer {token}"}
    return config


async def _mcp_tools(server_name: str, config: dict):
    client = MultiServerMCPClient(config)
    tools = await client.get_tools()
    print(f"Loaded {len(tools)} {server_name} tools")
    print(f"Tools Available\n{[tool.name for tool in tools]}")
    return tools


async def _supabase_tools():
    return await _mcp_tools("Supabase", _supabase_mcp_config())


async def _google_sheet_tools():
    config = load_mcp_config("google-sheets")
    if "google-sheets" not in config:
        raise RuntimeError("Google Sheets MCP is not configured.")
    tools = await _mcp_tools("Google Sheets", config)
    hidden = {"update_cells"}
    return [tool for tool in tools if tool.name not in hidden]


async def create_supervisor_tools(clerk_id: str):
    """Wrap the Supabase and Google Sheets agents as tools for the supervisor.

    Each specialist connects to its MCP server only when the supervisor calls it.
    """

    @tool
    async def query_supabase(query: str) -> str:
        """Trả lời câu hỏi về database Supabase: khách hàng, sản phẩm, báo giá, đơn hàng, tồn kho, công nợ.

        Args:
            query: Câu hỏi đầy đủ cần tra trong database.
        """
        try:
            supabase_agent = create_agent(
                model=model,
                tools=await _supabase_tools(),
                system_prompt=sales_database_prompt(clerk_id),
            ).with_config({
                "run_name": "chat_supabase_agent",
                "tags": ["chat", "supabase"],
            })
            result = await supabase_agent.ainvoke(
                {"messages": [HumanMessage(query)]},
            )
            return _message_text(result["messages"][-1])
        except Exception as exc:
            return f"Không tra được database: {_error_text(exc)}"

    @tool
    async def query_google_sheets(query: str) -> str:
        """Trả lời câu hỏi về Google Sheets: file bảng tính, dữ liệu sheet, giá và tạo bảng tính.

        Args:
            query: Câu hỏi đầy đủ cần tra trong Google Sheets.
        """
        try:
            sheets_agent = create_agent(
                model=model,
                tools=await _google_sheet_tools(),
                system_prompt=GOOGLE_SHEETS_PROMPT,
            ).with_config({
                "run_name": "chat_google_sheets_agent",
                "tags": ["chat", "google-sheets"],
            })
            result = await sheets_agent.ainvoke(
                {"messages": [HumanMessage(query)]},
            )
            return _message_text(result["messages"][-1])
        except Exception as exc:
            return f"Không tra được Google Sheets: {_error_text(exc)}"

    return [query_supabase, query_google_sheets]


async def create_chat_supervisor(clerk_id: str):
    """Supervisor that delegates database and spreadsheet questions."""
    supervisor_tools = await create_supervisor_tools(clerk_id)
    return create_agent(
        model=model,
        tools=supervisor_tools,
        system_prompt=chat_supervisor_prompt(),
        checkpointer=checkpointer,
    ).with_config({
        "recursion_limit": 12,
        "run_name": "chat_supervisor",
        "tags": ["chat", "supervisor"],
    })


async def _prepare_supervisor(clerk_id: str, thread_id: str):
    supervisor = await create_chat_supervisor(clerk_id)
    config = {"configurable": {"thread_id": thread_id}}
    state = await supervisor.aget_state(config)
    repairs = _repair_dangling_tool_calls(state.values.get("messages") or [])
    if repairs:
        await supervisor.aupdate_state(config, {"messages": repairs}, as_node="tools")
    return supervisor, config


async def stream_chat_supervisor(
    query: str,
    clerk_id: str,
    thread_id: str,
) -> AsyncIterator[dict]:
    """Yield status updates, then token deltas for the supervisor's own answer."""
    yield {"type": "status", "text": "Đang xử lý..."}
    supervisor, config = await _prepare_supervisor(clerk_id, thread_id)
    announced: set[str] = set()
    async for mode, data in supervisor.astream(
        {"messages": [HumanMessage(query)]},
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "updates":
            if not isinstance(data, dict):
                continue
            for update in data.values():
                for message in _messages_from_update(update):
                    for name in _tool_names(message):
                        if name in announced:
                            continue
                        announced.add(name)
                        yield {
                            "type": "status",
                            "text": _TOOL_STATUS.get(name, "Đang xử lý..."),
                        }
            continue

        if not isinstance(data, tuple) or len(data) != 2:
            continue
        message, metadata = data
        if not _is_supervisor_turn(metadata if isinstance(metadata, dict) else None):
            continue
        for name in _tool_names(message):
            if name in announced:
                continue
            announced.add(name)
            yield {
                "type": "status",
                "text": _TOOL_STATUS.get(name, "Đang xử lý..."),
            }
        if not isinstance(message, AIMessageChunk):
            continue
        text = _chunk_text(message)
        if text:
            yield {"type": "delta", "text": text}


async def run_chat_supervisor(query: str, clerk_id: str, thread_id: str) -> str:
    parts = []
    async for event in stream_chat_supervisor(query, clerk_id, thread_id):
        if event.get("type") == "delta":
            parts.append(event.get("text") or "")
    return "".join(parts).strip()
