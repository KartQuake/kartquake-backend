# backend/schemas.py
from typing import Optional, List
import uuid

from pydantic import BaseModel

from .models import PlanConstraints


class ChatRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    message: str


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    reply: str
    constraints: PlanConstraints


class PlanItem(BaseModel):
    raw_text: str
    canonical_category: Optional[str] = None
    quantity: int = 1
    estimated_price: Optional[float] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    travel_minutes: Optional[int] = None


class StoreInfo(BaseModel):
    id: str
    name: str
    distance_minutes: int


class StorePlan(BaseModel):
    label: str
    stores: List[StoreInfo]
    number_of_stores: int
    total_price: float
    travel_minutes: int


class PlanBuildRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    items: List[PlanItem]
    # If caller wants to override memory explicitly:
    override_constraints: Optional[PlanConstraints] = None


class PlanBuildResponse(BaseModel):
    constraints_used: PlanConstraints
    plans: List[StorePlan]
