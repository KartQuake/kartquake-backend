# app/models/trip_session.py

from __future__ import annotations

from uuid import uuid4, UUID
from datetime import datetime
from typing import Optional, Dict, Any, Literal

import re
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import Session

from app.db.base import Base


class TripSession(Base):
    """
    One 'trip' session per user. For now we keep a single active session per user.
    It stores planning constraints as JSON.
    """
    __tablename__ = "trip_sessions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    constraints = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PlanConstraints(BaseModel):
    """
    Structured representation of trip constraints that the assistant 'remembers'.
    These are saved in TripSession.constraints as JSON.
    """
    max_stores: Optional[int] = None
    avoid_costco: bool = False
    include_cheapest_gas: bool = False
    optimize_for: Literal["balanced", "cheapest_overall", "fastest_drive"] = "balanced"
    must_include_costco: bool = False

    class Config:
        from_attributes = True


# ---------------------------------------------------------
# Session helpers
# ---------------------------------------------------------

def get_or_create_trip_session(db: Session, user_id: UUID) -> TripSession:
    """
    Return the single current trip session for this user, creating one if needed.
    """
    existing = (
        db.query(TripSession)
        .filter(TripSession.user_id == user_id)
        .order_by(TripSession.created_at.desc())
        .first()
    )
    if existing:
        return existing

    sess = TripSession(user_id=user_id)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def load_constraints(sess: TripSession) -> PlanConstraints:
    data = sess.constraints or {}
    try:
        return PlanConstraints(**data)
    except Exception:
        return PlanConstraints()


def save_constraints(db: Session, sess: TripSession, constraints: PlanConstraints) -> TripSession:
    sess.constraints = constraints.model_dump()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


# ---------------------------------------------------------
# Constraint parsing from natural language
# ---------------------------------------------------------

def _parse_int_after(text: str, trigger_words: list[str]) -> Optional[int]:
    """
    Try patterns like "only 2 stores", "max 3 stores", "limit to 2".
    """
    for word in trigger_words:
        # allow optional "to" after word, e.g. "limit to 2 stores"
        pattern = rf"{word}\s+(?:to\s+)?(\d+)"
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def parse_constraints_from_text(
    text: str,
    existing: Optional[PlanConstraints] = None,
) -> PlanConstraints:
    """
    Update PlanConstraints based on natural-language text.

    Examples we want to catch:
      - "only 2 stores" / "limit to 2 stores" / "max 2 stores" / "1 store only"
      - "avoid costco", "no costco"
      - "cheapest gas also", "cheap gas"
      - "cheapest overall"
      - "fastest drive", "shortest drive"
      - "I only want costco + one grocery store"
    """
    t = text.lower()
    c = existing or PlanConstraints()

    # -------- max_stores: "only 2 stores", "limit to 2", "max 2 stores", "1 store only" --------
    n = _parse_int_after(t, ["only", "max", "at most", "no more than", "limit"])
    if n is not None:
        c.max_stores = n

    # Special pattern: "1 store only"
    m_one_store = re.search(r"\b1\s+store\s+only\b", t)
    if m_one_store:
        c.max_stores = 1

    # "fewest stores" – interpret as prefer fewer stores, but no strict number
    # We don't have a field for that yet, so we just let the LLM prefer fewer in its reasoning.

    # -------- avoid Costco --------
    if ("avoid costco" in t) or ("no costco" in t) or ("don't go to costco" in t) or ("dont go to costco" in t):
        c.avoid_costco = True
        c.must_include_costco = False  # cannot both avoid and must-include

    # -------- must include Costco + one grocery store --------
    if (
        "only costco" in t
        or "costco + one grocery" in t
        or "costco and one grocery" in t
        or "costco and one other grocery" in t
        or "i only want costco + one grocery store" in t
    ):
        c.must_include_costco = True
        c.avoid_costco = False
        c.max_stores = 2

    # -------- cheapest gas --------
    if "cheapest gas" in t or "cheap gas" in t:
        c.include_cheapest_gas = True

    # -------- optimize_for: cheapest vs fastest --------
    if (
        "cheapest overall" in t
        or "lowest total cost" in t
        or "as cheap as possible" in t
        or "best price" in t
    ):
        c.optimize_for = "cheapest_overall"
    elif (
        "fastest drive" in t
        or "shortest drive" in t
        or "fastest route" in t
        or "as fast as possible" in t
    ):
        c.optimize_for = "fastest_drive"

    # Otherwise, keep "balanced"

    return c
