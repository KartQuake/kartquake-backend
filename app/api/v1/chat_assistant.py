from typing import List, Optional
from uuid import UUID, uuid4
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from openai import OpenAI

from app.db.session import SessionLocal
from app.models.user import User
from app.models.item_intent import ItemIntent, ItemIntentRead
from app.models.chat import ChatSession, ChatMessage


router = APIRouter(prefix="/chat", tags=["chat-assistant"])


# ========== DB DEPENDENCY ==========


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== Pydantic schemas for assistant endpoint ==========


class ChatAssistantRequest(BaseModel):
    user_id: UUID
    message: str
    session_id: Optional[UUID] = None  # optional existing session to continue


class ChatAssistantResponse(BaseModel):
    session_id: UUID
    reply: str
    items: List[ItemIntentRead]


# ========== OpenAI client & system prompt ==========


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("[WARN] OPENAI_API_KEY is not set in environment; /chat/assistant will fail.")
client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are Kartquake, an AI shopping assistant.

Your job:
- Help the user build and refine a shopping list.
- Ask clarifying questions when details are missing (e.g., milk fat %, lactose free, iPad storage, color).
- Keep your answers short, clear, and conversational.

Important:
- The backend will separately parse the user's messages into structured item_intents and compute store plans.
- You DO NOT need to output JSON or structured data, just talk naturally.
- When the user adds or changes items, respond as a friendly assistant acknowledging and asking any needed follow-ups.
"""


# ========== Helper functions ==========


def get_or_create_session(db: Session, user_id: UUID, session_id: Optional[UUID]) -> ChatSession:
    """
    If session_id is provided and belongs to user, return it.
    Otherwise create a new session.
    """
    if session_id:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .first()
        )
        if session:
            return session

    # Create a new session
    new_session = ChatSession(
        id=uuid4(),
        user_id=user_id,
        title=None,
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return new_session


def get_message_history(db: Session, session: ChatSession, limit: int = 10):
    """
    Return the last N messages formatted for OpenAI chat.
    """
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    # Keep only the last `limit` messages
    messages = messages[-limit:]

    history = []
    for m in messages:
        role = "user" if m.role == "user" else "assistant"
        history.append({"role": role, "content": m.content})
    return history


def call_openai_chat(messages):
    """
    Call OpenAI with the given message history.
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in environment")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
    )

    reply = response.choices[0].message.content.strip()
    return reply


def trigger_parse_to_item_intents(user_id: UUID, message: str):
    """
    Call our own /chat/parse endpoint to update item_intents for this user.
    This reuses the existing parsing logic and DB writes.
    """
    base_url = os.getenv("KARTQUAKE_BACKEND_URL", "http://127.0.0.1:8000")
    url = f"{base_url}/chat/parse"

    payload = {"user_id": str(user_id), "message": message}
    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
    except Exception as e:
        # For now just log; we don't want to block the assistant reply on this.
        print(f"[WARN] Failed to call /chat/parse: {e}")


def get_user_items(db: Session, user_id: UUID) -> List[ItemIntent]:
    """
    Fetch all item_intents for this user (you can later filter by status or session).
    """
    return (
        db.query(ItemIntent)
        .filter(ItemIntent.user_id == user_id)
        .order_by(ItemIntent.created_at.asc())
        .all()
    )


# ========== MAIN ENDPOINT ==========


@router.post("/assistant", response_model=ChatAssistantResponse)
def chat_with_assistant(payload: ChatAssistantRequest, db: Session = Depends(get_db)):
    # 1) Validate user
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2) Get or create session
    session = get_or_create_session(db, payload.user_id, payload.session_id)

    # 3) Store user message
    user_msg = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        user_id=payload.user_id,
        role="user",
        content=payload.message,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # 4) Build message history for OpenAI
    history = get_message_history(db, session, limit=10)
    # Prepend system message
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    # 5) Call OpenAI to get assistant reply
    try:
        reply_text = call_openai_chat(messages)
    except Exception as e:
        error_msg = f"Error talking to assistant: {e}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

    # 6) Store assistant message
    assistant_msg = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        user_id=payload.user_id,
        role="assistant",
        content=reply_text,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    # 7) Trigger parsing to update item_intents
    trigger_parse_to_item_intents(payload.user_id, payload.message)

    # 8) Fetch updated items for the user
    items = get_user_items(db, payload.user_id)
    items_read = [ItemIntentRead.from_orm(it) for it in items]

    # 9) Return reply + updated items + session_id
    return ChatAssistantResponse(
        session_id=session.id,
        reply=reply_text,
        items=items_read,
    )
