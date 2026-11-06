import os
import uuid
from collections.abc import AsyncIterator

from langchain.agents import create_agent
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver

from src.rag.retrieval.index import retrieve_context
from src.rag.retrieval.utils import get_ready_documents, public_document_excerpts
from src.scripts.prompts import (
    GOOGLE_SHEETS_PROMPT,
    WEB_SEARCH_PROMPT,
    chat_supervisor_prompt,
    document_assistant_prompt,
    sales_database_prompt,
)
from src.scripts.utils import load_mcp_config
from src.services.chatHistory import (
    discard_chat_thread,
    list_chat_messages,
    open_chat_thread,
    save_chat_exchange,
)
from src.services.googleSheetsAuth import sheets_connection_status

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


_TOOL_STATUS = {
    "query_supabase": "Đang tra cứu database...",
    "query_documents": "Đang đọc tài liệu...",
    "search_uploaded_documents": "Đang đọc tài liệu...",
    "query_google_sheets": "Đang tra cứu Google Sheets...",
    "query_web": "Đang tìm trên web...",
    "tavily_search": "Đang tìm trên web...",
}


def _is_supervisor_turn(metadata: dict | None) -> bool:
    tags = (metadata or {}).get("tags") or []
    if "supabase" in tags or "google-sheets" in tags or "documents" in tags or "web" in tags:
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


def _format_document_context(texts: list, tables: list, citations: list) -> str:
    if not texts and not tables:
        return "Không tìm thấy nội dung liên quan trong tài liệu đã tải."
    blocks = []
    for index, text in enumerate(texts, 1):
        blocks.append(f"Đoạn {index}\n{text.strip()}")
    for index, table in enumerate(tables, 1):
        blocks.append(f"Bảng {index}\n{table}")
    sources = []
    for citation in citations:
        filename = citation.get("filename") or "Tài liệu"
        page = citation.get("page")
        page_label = f", trang {page}" if page not in (None, "", "Unknown") else ""
        sources.append(f"- {filename}{page_label}")
    if sources:
        blocks.append("Nguồn:\n" + "\n".join(sources))
    return "\n\n".join(blocks)


async def create_supervisor_tools(
    clerk_id: str,
    document_ids: list[str] | None = None,
    excerpts_out: list | None = None,
):
    """Wrap the database, document, spreadsheet, and web agents as supervisor tools.

    Each specialist connects to its own tools only when the supervisor calls it.
    document_ids limits document search to the files the user selected.
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
    def search_uploaded_documents(query: str) -> str:
        """Tìm các đoạn liên quan trong tài liệu đã tải của người dùng.

        Args:
            query: Câu hỏi hoặc cụm từ cần tìm trong tài liệu.
        """
        try:
            if document_ids is None:
                ready = get_ready_documents(clerk_id)
            else:
                ready = get_ready_documents(clerk_id, document_ids)
            if not ready:
                if document_ids is None:
                    return "Chưa có tài liệu nào đã embed xong. Hãy tải tài liệu ở trang Tài liệu."
                return "Các tài liệu đã chọn chưa sẵn sàng hoặc không còn."
            selected_names = [row["filename"] for row in ready]
            texts, _images, tables, citations = retrieve_context(
                clerk_id,
                query,
                document_ids=None if document_ids is None else [row["id"] for row in ready],
            )
            found = public_document_excerpts(citations)
            if excerpts_out is not None and found:
                excerpts_out.clear()
                excerpts_out.extend(found)
            context = _format_document_context(texts, tables, citations)
            if document_ids is None:
                return context
            return "Chỉ tìm trong: " + ", ".join(selected_names) + "\n\n" + context
        except Exception as exc:
            return f"Không đọc được tài liệu: {_error_text(exc)}"

    @tool
    async def query_documents(query: str) -> str:
        """Trả lời câu hỏi về tài liệu đã tải: PDF, Word, PowerPoint, TXT, Markdown, bảng giá, catalogue, hợp đồng.

        Args:
            query: Câu hỏi đầy đủ cần tìm trong tài liệu đã tải.
        """
        try:
            document_agent = create_agent(
                model=model,
                tools=[search_uploaded_documents],
                system_prompt=document_assistant_prompt(
                    None
                    if document_ids is None
                    else [row["filename"] for row in get_ready_documents(clerk_id, document_ids)]
                ),
            ).with_config({
                "run_name": "chat_document_agent",
                "tags": ["chat", "documents"],
            })
            result = await document_agent.ainvoke(
                {"messages": [HumanMessage(query)]},
            )
            return _message_text(result["messages"][-1])
        except Exception as exc:
            return f"Không đọc được tài liệu: {_error_text(exc)}"

    @tool
    async def query_google_sheets(query: str) -> str:
        """Trả lời câu hỏi về Google Sheets: file bảng tính, dữ liệu sheet, giá và tạo bảng tính.

        Args:
            query: Câu hỏi đầy đủ cần tra trong Google Sheets.
        """
        if not sheets_connection_status().get("connected"):
            return (
                "Google Sheets chưa đăng nhập hoặc token đã hết hạn. "
                "Hãy đăng nhập lại Google Sheets trên trang Trợ lý Sales."
            )
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
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return f"Không tra được Google Sheets: {_error_text(exc)}"

    @tool
    async def query_web(query: str) -> str:
        """Tìm thông tin công khai trên internet: tin tức, công ty, giá thị trường, quy định, địa chỉ, website.

        Args:
            query: Câu hỏi đầy đủ cần tìm trên web.
        """
        try:
            web_agent = create_agent(
                model=model,
                tools=[TavilySearch(max_results=5, search_depth="advanced")],
                system_prompt=WEB_SEARCH_PROMPT,
            ).with_config({
                "run_name": "chat_web_agent",
                "tags": ["chat", "web"],
            })
            result = await web_agent.ainvoke(
                {"messages": [HumanMessage(query)]},
            )
            return _message_text(result["messages"][-1])
        except Exception as exc:
            return f"Không tìm được trên web: {_error_text(exc)}"

    return [query_supabase, query_documents, query_google_sheets, query_web]


async def create_chat_supervisor(
    clerk_id: str,
    document_ids: list[str] | None = None,
    excerpts_out: list | None = None,
):
    """Supervisor that delegates database, document, spreadsheet, and web questions."""
    selected_names = None
    if document_ids is not None:
        selected_names = [
            row["filename"] for row in get_ready_documents(clerk_id, document_ids)
        ]
    supervisor_tools = await create_supervisor_tools(clerk_id, document_ids, excerpts_out)
    return create_agent(
        model=model,
        tools=supervisor_tools,
        system_prompt=chat_supervisor_prompt(selected_names),
        checkpointer=checkpointer,
    ).with_config({
        "recursion_limit": 12,
        "run_name": "chat_supervisor",
        "tags": ["chat", "supervisor"],
    })


def _history_messages(clerk_id: str, conversation_id: str, query: str) -> list:
    """Replay this conversation, then the new question.

    Each turn uses a new checkpoint so this history is not appended twice.
    """
    messages = []
    for row in list_chat_messages(clerk_id, conversation_id, limit=40):
        content = (row.get("content") or "").strip()
        if not content:
            continue
        if row.get("role") == "assistant":
            messages.append(AIMessage(content))
        else:
            messages.append(HumanMessage(content))
    messages.append(HumanMessage(query))
    return messages


async def _prepare_supervisor(
    clerk_id: str,
    document_ids: list[str] | None = None,
    excerpts_out: list | None = None,
):
    supervisor = await create_chat_supervisor(clerk_id, document_ids, excerpts_out)
    config = {"configurable": {"thread_id": f"{clerk_id}:{uuid.uuid4()}"}}
    return supervisor, config


async def stream_chat_supervisor(
    query: str,
    clerk_id: str,
    thread_id: str,
    document_ids: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Yield the conversation id, status updates, then the supervisor's answer."""
    conversation_id = thread_id.strip()
    thread, created = open_chat_thread(clerk_id, conversation_id or None, query)
    yield {
        "type": "thread",
        "id": thread["id"],
        "title": thread["title"],
        "updated_at": thread["updated_at"],
    }
    yield {"type": "status", "text": "Đang xử lý..."}
    excerpts: list[dict] = []
    supervisor, config = await _prepare_supervisor(clerk_id, document_ids, excerpts)
    prior_messages = _history_messages(clerk_id, thread["id"], query)
    parts: list[str] = []
    try:
        async for event in _stream_supervisor_turn(supervisor, config, prior_messages):
            if event.get("type") == "delta" and event.get("text"):
                parts.append(event["text"])
            yield event
    except Exception:
        if created:
            discard_chat_thread(clerk_id, thread["id"])
        raise
    reply = "".join(parts).strip()
    if reply and excerpts:
        yield {"type": "citations", "items": excerpts}
    if reply:
        saved = save_chat_exchange(clerk_id, thread["id"], query, reply, excerpts)
        yield {
            "type": "thread",
            "id": saved["id"],
            "title": saved["title"],
            "updated_at": saved["updated_at"],
        }
    elif created:
        discard_chat_thread(clerk_id, thread["id"])


async def _stream_supervisor_turn(supervisor, config, prior_messages):
    announced: set[str] = set()
    async for mode, data in supervisor.astream(
        {"messages": prior_messages},
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
