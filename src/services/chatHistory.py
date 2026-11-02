import re
import uuid
from datetime import datetime, timedelta, timezone

from src.services.supabase import supabase
from src.services.users import ensure_user

THREADS = "sales_chat_threads"
MESSAGES = "sales_chat_messages"
HISTORY_LIMIT = 200
THREAD_LIMIT = 100


def _title_from_question(question: str) -> str:
    compact = re.sub(r"\s+", " ", question).strip()
    if not compact:
        return "Cuộc trò chuyện"
    if len(compact) <= 72:
        return compact
    return compact[:69].rstrip() + "…"


def _parse_thread_id(thread_id: str) -> str | None:
    try:
        return str(uuid.UUID(thread_id))
    except (TypeError, ValueError):
        return None


def list_chat_threads(clerk_id: str) -> list[dict]:
    ensure_user(clerk_id)
    result = (
        supabase.table(THREADS)
        .select("id, title, updated_at")
        .eq("clerk_id", clerk_id)
        .order("updated_at", desc=True)
        .limit(THREAD_LIMIT)
        .execute()
    )
    return list(result.data or [])


def get_chat_thread(clerk_id: str, thread_id: str) -> dict | None:
    parsed = _parse_thread_id(thread_id)
    if not parsed:
        return None
    result = (
        supabase.table(THREADS)
        .select("id, title, updated_at")
        .eq("id", parsed)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def create_chat_thread(clerk_id: str, title: str) -> dict:
    ensure_user(clerk_id)
    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase.table(THREADS)
        .insert(
            {
                "clerk_id": clerk_id,
                "title": title or "Cuộc trò chuyện",
                "created_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    return result.data[0]


def open_chat_thread(clerk_id: str, thread_id: str | None, question: str) -> tuple[dict, bool]:
    if thread_id:
        existing = get_chat_thread(clerk_id, thread_id)
        if not existing:
            raise LookupError("Chat thread not found.")
        return existing, False
    return create_chat_thread(clerk_id, _title_from_question(question)), True


def discard_chat_thread(clerk_id: str, thread_id: str) -> None:
    parsed = _parse_thread_id(thread_id)
    if not parsed:
        return
    supabase.table(THREADS).delete().eq("id", parsed).eq("clerk_id", clerk_id).execute()


def list_chat_messages(clerk_id: str, thread_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    if not get_chat_thread(clerk_id, thread_id):
        raise LookupError("Chat thread not found.")
    result = (
        supabase.table(MESSAGES)
        .select("id, role, content, created_at")
        .eq("thread_id", thread_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = list(result.data or [])
    rows.reverse()
    return rows


def save_chat_exchange(clerk_id: str, thread_id: str, question: str, answer: str) -> dict:
    question = question.strip()
    answer = answer.strip()
    thread = get_chat_thread(clerk_id, thread_id)
    if not thread:
        raise LookupError("Chat thread not found.")
    if not question or not answer:
        return thread
    asked_at = datetime.now(timezone.utc)
    supabase.table(MESSAGES).insert(
        [
            {
                "clerk_id": clerk_id,
                "thread_id": thread["id"],
                "role": "user",
                "content": question,
                "created_at": asked_at.isoformat(),
            },
            {
                "clerk_id": clerk_id,
                "thread_id": thread["id"],
                "role": "assistant",
                "content": answer,
                "created_at": (asked_at + timedelta(milliseconds=1)).isoformat(),
            },
        ]
    ).execute()
    updated_at = datetime.now(timezone.utc).isoformat()
    supabase.table(THREADS).update({"updated_at": updated_at}).eq("id", thread["id"]).execute()
    return {**thread, "updated_at": updated_at}
