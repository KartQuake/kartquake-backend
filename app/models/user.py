# app/models/user.py

from datetime import datetime
from typing import Optional, List
from uuid import uuid4, UUID as UUIDType

from sqlalchemy import Column, String, DateTime, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pydantic import BaseModel, EmailStr

from app.db.base_class import Base


# ============================================================
# SQLAlchemy model
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)

    # NEW: plan + membership / free-tier fields
    # -----------------------------------------
    # plan: "free" or "premium" for now
    plan = Column(String, nullable=False, default="free")

    # If user already has a real Costco membership
    has_costco_membership = Column(Boolean, nullable=False, default=False)

    # If they bought your digital Costco add-on
    has_costco_addon = Column(Boolean, nullable=False, default=False)

    # Free tier limits
    free_items_limit = Column(Integer, nullable=False, default=5)
    free_plan_runs_limit = Column(Integer, nullable=False, default=5)
    free_plan_runs_used = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    item_intents = relationship(
        "ItemIntent",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    store_memberships = relationship(
        "UserStoreMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    watchlist_items = relationship(
        "WatchlistItem",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ============================================================
# Pydantic schemas
# ============================================================

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    zip_code: Optional[str] = None


class UserCreate(UserBase):
    """For now, new users always start as free tier with defaults."""
    pass


class UserUpdate(BaseModel):
    # Let you change name/zip only for now.
    # (You could optionally add plan & membership fields here later
    #  if you want an admin UI to edit them.)
    name: Optional[str] = None
    zip_code: Optional[str] = None


class UserRead(UserBase):
    id: UUIDType

    # Expose the new fields on GET /users
    plan: str
    has_costco_membership: bool
    has_costco_addon: bool
    free_items_limit: int
    free_plan_runs_limit: int
    free_plan_runs_used: int

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2 replacement for orm_mode = True
