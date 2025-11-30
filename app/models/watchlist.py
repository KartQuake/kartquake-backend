# app/models/watchlist.py

from datetime import datetime
from typing import Optional
from uuid import uuid4, UUID as UUIDType

from sqlalchemy import Column, DateTime, Boolean, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pydantic import BaseModel

from app.db.base_class import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # We watch a concrete ItemIntent, so we can track its price in plans
    item_intent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("item_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_active = Column(Boolean, default=True)

    # Price tracking (from plan builder)
    last_price = Column(Numeric(10, 2), nullable=True)
    previous_price = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Lightweight relationships (no back_populates – no need to touch User/ItemIntent)
    user = relationship("User")
    item_intent = relationship("ItemIntent")


# ------------- Pydantic schemas (for API responses) -----------------


class WatchlistItemRead(BaseModel):
    id: UUIDType
    user_id: UUIDType
    item_intent_id: UUIDType
    is_active: bool
    last_price: Optional[float] = None
    previous_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WatchedItemWithDrop(BaseModel):
    item_id: UUIDType
    raw_text: str
    canonical_category: Optional[str] = None
    last_price: Optional[float] = None
    previous_price: Optional[float] = None
    price_drop: Optional[float] = None

    class Config:
        from_attributes = True
