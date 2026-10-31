import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from src.agents.chat_supervisor_agent import stream_chat_supervisor
from src.services.clerkAuth import get_current_user_clerk_id

router = APIRouter(tags=["chatRoutes"])


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=2)
    thread_id: str = "default"


def _error_text(exc: BaseException) -> str:
    exceptions = getattr(exc, "exceptions", None)
    if exceptions:
        return "; ".join(_error_text(item) for item in exceptions)
    return str(exc)


@router.post("")
@router.post("/")
async def chat(
    request: ChatRequest,
    user_clerk_id: str = Depends(get_current_user_clerk_id),
):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt!")

    thread_id = request.thread_id.strip() or user_clerk_id

    async def events():
        try:
            async for event in stream_chat_supervisor(
                request.prompt,
                clerk_id=user_clerk_id,
                thread_id=thread_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield 'data: {"type": "done"}\n\n'
        except Exception as exc:
            payload = {"type": "error", "text": f"Server error: {_error_text(exc)}"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
