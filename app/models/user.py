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

    # Email is now OPTIONAL so we can support anonymous / guest users
    # and users created first via OAuth before we confirm their email.
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)

    # Auth provider metadata
    # ----------------------
    # "anonymous"  -> created via guest signup
    # "google"     -> created/linked via Google OAuth
    # "apple"      -> created/linked via Apple OAuth
    auth_provider = Column(String, nullable=False, default="anonymous")

    # Provider-specific subject / user id (e.g. Google "sub" claim, Apple "sub")
    auth_provider_subject = Column(String, nullable=True, index=True)

    # Plan + membership / free-tier fields
    # ------------------------------------
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
    # All optional to support:
    # - anonymous users (no email yet)
    # - progressively adding profile info
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    zip_code: Optional[str] = None


class UserCreate(UserBase):
    """
    Used when creating a user (guest signup, Google/Apple sign-in, etc).

    For guest signup from the frontend we’ll typically send:
      { "auth_provider": "anonymous" }

    For Google/Apple callback handlers you might build:
      {
        "email": "...",
        "name": "...",
        "auth_provider": "google",
        "auth_provider_subject": "<google-sub-claim>"
      }
    """
    auth_provider: Optional[str] = "anonymous"      # "anonymous" | "google" | "apple"
    auth_provider_subject: Optional[str] = None     # provider-specific user id


class UserUpdate(BaseModel):
    # Let you change profile info for now.
    # You can expand this later for plan/membership admin changes.
    name: Optional[str] = None
    zip_code: Optional[str] = None
    has_costco_membership: Optional[bool] = None
    has_costco_addon: Optional[bool] = None


class UserRead(UserBase):
    id: UUIDType

    # Expose the new fields on GET /users / auth responses
    plan: str
    has_costco_membership: bool
    has_costco_addon: bool
    free_items_limit: int
    free_plan_runs_limit: int
    free_plan_runs_used: int

    auth_provider: str
    auth_provider_subject: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        # Pydantic v2 option (replaces orm_mode = True)
        from_attributes = True
