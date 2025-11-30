# backend/models.py
import uuid
from datetime import datetime
from typing import Optional, Literal, Dict, Any

from sqlmodel import SQLModel, Field, Column, JSON
from pydantic import BaseModel


class PlanConstraints(BaseModel):
    """
    What the assistant remembers for 'this trip'.
    This is stored as JSON on TripSession.
    """
    max_stores: Optional[int] = None
    avoid_costco: bool = False
    include_cheapest_gas: bool = False
    optimize_for: Literal["balanced", "cheapest_overall", "fastest_drive"] = "balanced"
    must_include_costco: bool = False
    # You can extend later with:
    # avoid_store_names: list[str] = []
    # must_include_store_names: list[str] = []


class TripSession(SQLModel, table=True):
    """
    One 'trip' session. Constraints for that trip are stored here.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Stored as raw dict in DB, converted to PlanConstraints in code
    constraints: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
    )
