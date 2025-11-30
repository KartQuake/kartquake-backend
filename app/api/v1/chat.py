# app/api/v1/chat.py

from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from openai import OpenAI

from app.db.session import get_db
from app.models.user import User
from app.models.item_intent import ItemIntent
from app.models.trip_session import (
    get_or_create_trip_session,
    load_constraints,
    save_constraints,
    parse_constraints_from_text,
    PlanConstraints,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# -----------------------------
# OpenAI client
# -----------------------------
client = OpenAI()  # uses OPENAI_API_KEY from environment


# -----------------------------
# Pydantic models
# -----------------------------

class ChatAssistantRequest(BaseModel):
  user_id: UUID
  message: str


class ItemIntentOut(BaseModel):
  id: UUID
  user_id: UUID
  raw_text: str
  canonical_category: Optional[str]
  quantity: int
  status: str
  attributes: Dict[str, Any]
  created_at: Any

  class Config:
      from_attributes = True  # Pydantic v2


class ChatAssistantResponse(BaseModel):
  session_id: Optional[UUID]
  reply: str
  items: List[ItemIntentOut]


# -----------------------------
# Helper: detect "looks like shopping"
# -----------------------------

def looks_like_shopping_request(msg: str) -> bool:
  text = msg.lower()
  keywords = [
      "milk", "egg", "eggs", "cereal", "ipad", "tablet",
      "tide", "pods", "detergent", "bread", "cheese", "butter",
      "carton", "gallon", "kg", "lb", "pound", "pack", "packs",
      "bag", "bags"
  ]
  if any(k in text for k in keywords):
      return True
  # if message has a number, very often it's a quantity
  if any(ch.isdigit() for ch in msg):
      return True
  return False


# -----------------------------
# LLM helper
# -----------------------------

def call_llm_for_intents(user_message: str) -> Dict[str, Any]:
  """
  Ask the LLM to:
  - understand the user's shopping request,
  - decide on product intents,
  - return JSON with:
      {
        "reply": "<natural language reply>",
        "intents": [
          {
            "raw_text": "<short product phrase like '2% milk'>",
            "canonical_category": "milk" | "eggs" | "cereal" | "tablet" | "detergent" | "other",
            "quantity": <int>,
            "attributes": { ... },
            "needs_clarification": <bool>
          }, ...
        ]
      }
  """

  system_prompt = """
You are Kartquake, an AI shopping assistant.

GOALS:
- Talk conversationally like ChatGPT.
- Understand the user's shopping request and break it into product "intents".
- Each intent is ONE product / line item for a shopping list.
- Ask FOLLOW-UP questions when needed (brand, size, flavor, quantity, etc.).
- DO NOT ignore the user. Always give a useful reply.

VERY IMPORTANT – raw_text:
- "raw_text" must be a short product phrase ONLY, not the whole sentence.
  Example:
    User: "I need 2% milk"
    → raw_text: "2% milk"
    NOT: "I need 2% milk"

CATEGORIES:
- canonical_category must be one of:
    "milk", "eggs", "cereal", "tablet", "detergent", "other"

ATTRIBUTES:
- Put structured details in "attributes", for example:
    - volume: "1 gallon", "2L"
    - fat_level: "2%"
    - lactose_free: true/false
    - brand: "Kellogg", "Tide", "Apple"
    - storage: "256GB"
    - color: "space gray"
    - type: "pods"
    - egg_size: "large", etc.

needs_clarification:
- true if you need more info before safely adding this item,
- false if you are comfortable adding it as-is.

If the user message clearly describes an item with quantity and type,
you can set needs_clarification = false and confirm you added it.

If the user says something ambiguous like "1 gallon" with no context,
you MUST set needs_clarification = true and ask what product they mean.

If the user talks about planning preferences like "cheapest" or "1 store only",
you can return "intents": [] and just use "reply" to talk about planning.

OUTPUT FORMAT:
- You MUST respond with **ONLY** valid JSON (no extra text, no markdown).
- JSON object must have:
  - "reply": string
  - "intents": array of objects as described.
"""

  user_prompt = f"User message: {user_message}"

  response = client.chat.completions.create(
      model="gpt-4o-mini",
      temperature=0.3,
      response_format={"type": "json_object"},
      messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt},
      ],
  )

  content = response.choices[0].message.content
  data = json.loads(content)

  if "reply" not in data:
      data["reply"] = "Sorry, I had trouble formatting my answer."
  if "intents" not in data or not isinstance(data["intents"], list):
      data["intents"] = []

  norm_intents = []
  for intent in data["intents"]:
      if not isinstance(intent, dict):
          continue
      norm_intents.append(
          {
              "raw_text": intent.get("raw_text", "").strip(),
              "canonical_category": intent.get("canonical_category"),
              "quantity": int(intent.get("quantity", 1) or 1),
              "attributes": intent.get("attributes") or {},
              "needs_clarification": bool(intent.get("needs_clarification", False)),
          }
      )
  data["intents"] = norm_intents

  return data


# -----------------------------
# Main route
# -----------------------------


@router.post("/assistant", response_model=ChatAssistantResponse)
def chat_assistant(
  payload: ChatAssistantRequest,
  db: Session = Depends(get_db),
) -> ChatAssistantResponse:
  """
  LLM-powered assistant:
  - Calls OpenAI to interpret the message.
  - If any intent needs clarification: return the LLM reply, DO NOT write to DB.
  - Otherwise: create ItemIntent rows and return them with the reply.
  - Also: update per-user trip constraints (session memory for "this trip").
  """

  # 1. Ensure user exists
  user = db.query(User).filter(User.id == payload.user_id).first()
  if not user:
      raise HTTPException(status_code=404, detail="User not found")

  is_free = (user.plan or "free") == "free"

  # 2. Ensure / get trip session for this user
  trip_session = get_or_create_trip_session(db, user.id)
  existing_constraints: PlanConstraints = load_constraints(trip_session)

  message = payload.message.strip()
  if not message:
      # Even if message is empty, we still return the session_id so frontend can see it
      return ChatAssistantResponse(
          session_id=trip_session.id,
          reply="Tell me what you want to buy, like “2% milk” or “a dozen eggs”.",
          items=[],
      )

  # 3. Update constraints from this message (session memory for planning phrases)
  updated_constraints = parse_constraints_from_text(message, existing_constraints)
  if updated_constraints.model_dump() != existing_constraints.model_dump():
      save_constraints(db, trip_session, updated_constraints)

  # 4. Call LLM for intents
  try:
      llm_result = call_llm_for_intents(message)
  except Exception as e:
      raise HTTPException(
          status_code=500,
          detail=f"Error talking to assistant: {e}",
      )

  reply_text: str = llm_result.get("reply", "").strip()
  intents_data: List[Dict[str, Any]] = llm_result.get("intents", [])

  # 5. If LLM somehow returns nothing but the message looks like shopping,
  #    force a clarification instead of just saying "Okay."
  if not intents_data and looks_like_shopping_request(message):
      reply_text = (
          "Got it, you’re shopping. I didn’t fully catch the details – "
          "can you say something like “1 gallon of 2% lactose-free milk” "
          "or “3 packs of Kellogg Corn Flakes”?"
      )
      return ChatAssistantResponse(
          session_id=trip_session.id,
          reply=reply_text,
          items=[],
      )

  # 6. If any intent needs clarification -> just return message, no DB writes
  if any(intent.get("needs_clarification", False) for intent in intents_data):
      if not reply_text:
          reply_text = "I need a bit more detail before I add that to your list."
      return ChatAssistantResponse(
          session_id=trip_session.id,
          reply=reply_text,
          items=[],
      )

  # 7. If there are no intents (and not shopping-like), just return the reply
  if not intents_data:
      if not reply_text:
          reply_text = "Okay."
      return ChatAssistantResponse(
          session_id=trip_session.id,
          reply=reply_text,
          items=[],
      )

  # -----------------------------
  # 7b. FREE-TIER ENFORCEMENT (max 5 items)
  # -----------------------------
  slots_remaining: Optional[int] = None
  if is_free:
      limit = user.free_items_limit or 5
      existing_pending = (
          db.query(ItemIntent)
          .filter(ItemIntent.user_id == payload.user_id)
          .filter(ItemIntent.status == "pending")
          .count()
      )

      if existing_pending >= limit:
          # Already at or above limit: don't add more
          reply = (
              f"You’ve reached the free tier limit of {limit} items on your list. "
              "Upgrade to the premium plan to add unlimited items and multi-store planning."
          )
          return ChatAssistantResponse(
              session_id=trip_session.id,
              reply=reply,
              items=[],
          )

      slots_remaining = max(limit - existing_pending, 0)

  # 8. All intents are addable (subject to free tier slots) -> create ItemIntent rows
  saved_items: List[ItemIntent] = []

  # Determine which intents to actually persist
  intents_to_save = intents_data
  truncated = False
  if is_free and slots_remaining is not None:
      if len(intents_data) > slots_remaining:
          intents_to_save = intents_data[:slots_remaining]
          truncated = True

  for intent in intents_to_save:
      raw_text = intent.get("raw_text", "").strip()
      if not raw_text:
          continue

      canonical_category = intent.get("canonical_category")
      quantity = intent.get("quantity", 1)
      attributes = intent.get("attributes") or {}

      item = ItemIntent(
          id=uuid4(),
          user_id=payload.user_id,
          raw_text=raw_text,
          canonical_category=canonical_category,
          quantity=quantity,
          attributes=attributes,
          status="pending",
      )
      db.add(item)
      saved_items.append(item)

  db.commit()
  for item in saved_items:
      db.refresh(item)

  # 9. Build reply
  if not reply_text:
      if len(saved_items) == 1:
          reply_text = f'I added "{saved_items[0].raw_text}" to your list.'
      else:
          names = ", ".join(f'"{i.raw_text}"' for i in saved_items)
          reply_text = f"I added {len(saved_items)} items to your list: {names}."

  if is_free and truncated:
      reply_text += (
          " You’ve hit your free tier item limit. "
          "Upgrade to the premium plan to add more items."
      )

  return ChatAssistantResponse(
      session_id=trip_session.id,
      reply=reply_text,
      items=[ItemIntentOut.model_validate(i) for i in saved_items],
  )
